from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import tempfile
import threading
import uuid
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from simulanka.agent.context import (
    ContextBundle,
    ContextRef,
    ContextReferenceError,
    ContextSnapshotError,
    RefSet,
    compile_context,
    decide_context_delivery,
)
from simulanka.agent.harness import (
    DEFAULT_TIMEOUT,
    CommandRunner,
    HarnessError,
    parse_op_blocks,
)
from simulanka.agent.session import (
    ProviderAdapter,
    ProviderCapabilities,
    ProviderTurn,
    StreamRunner,
    TurnHandle,
    provider_adapters,
)
from simulanka.disagreements import disagreement_list, edge_payload
from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.events import Event, iter_events
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    CreatePortOp,
    DeleteEdgeOp,
    DeleteNodeOp,
    Receipt,
    RenameNodeOp,
    UpdateAttrsOp,
)
from simulanka.kernel.manifest import load_manifest
from simulanka.kernel.validator import ValidationError
from simulanka.layout.project import ProjectLayout
from simulanka.plan import PlanError, resolve_escalate
from simulanka.registry.builtin import DEFAULT_REGISTRY
from simulanka.registry.profiles import Registry
from simulanka.schema.entities import Edge, Node
from simulanka.server.action_resolver import ActionResolver, ActionTarget
from simulanka.server.agent_ops import apply_agent_ops
from simulanka.server.sessions import (
    Session,
    SessionNotFound,
    SessionStateError,
    archive_session,
    create_session,
    fork_session,
    list_sessions,
    load_session,
    read_session_events,
    recover_orphaned_sessions,
    session_record,
    session_tree_bindings,
    stream_session_turn,
)
from simulanka.storage.checkpoint import ensure_repo, repo_exists, tag_checkpoint
from simulanka.storage.entity_store import (
    iter_edges,
    iter_nodes,
    iter_ports,
    load_edge,
    load_node,
    node_exists,
)
from simulanka.trust import node_trust, provenance_chain

DEV_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

SSE_POLL_INTERVAL = 0.25  # seconds between event_log polls

# S4 file viewer: one human reads one page — a 1 MiB head is plenty, and a
# runaway training log must not take the browser down with it.
FILE_CONTENT_CAP = 1_048_576


@dataclass
class _ActiveTurn:
    """One app-local turn and its linearized terminal decision."""

    turn_id: str
    capabilities: ProviderCapabilities
    handle: TurnHandle | None = None
    stop_requested: bool = False
    terminal_result: Literal["provider", "interrupted"] | None = None


class _ActiveTurnRegistry:
    """Serialize send/stop/completion races per platform Session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: dict[str, _ActiveTurn] = {}

    def reserve(
        self,
        session_id: str,
        capabilities: ProviderCapabilities,
    ) -> _ActiveTurn | None:
        with self._lock:
            if session_id in self._turns:
                return None
            turn = _ActiveTurn(
                turn_id=uuid.uuid4().hex,
                capabilities=capabilities,
            )
            self._turns[session_id] = turn
            return turn

    def bind(self, session_id: str, turn: _ActiveTurn, handle: TurnHandle) -> None:
        with self._lock:
            if self._turns.get(session_id) is not turn:
                return
            turn.handle = handle
            stop_requested = turn.stop_requested
        if stop_requested:
            handle.cancel()

    def request_stop(
        self,
        session_id: str,
    ) -> Literal["stopping", "unsupported", "finished", "missing"]:
        with self._lock:
            turn = self._turns.get(session_id)
            if turn is None:
                return "missing"
            if not turn.capabilities.interrupt:
                return "unsupported"
            if turn.terminal_result is not None:
                return "finished"
            if turn.stop_requested:
                return "stopping"
            turn.stop_requested = True
            handle = turn.handle
        if handle is not None:
            handle.cancel()
        return "stopping"

    def claim_terminal(
        self,
        session_id: str,
        turn: _ActiveTurn,
    ) -> Literal["provider", "interrupted"]:
        with self._lock:
            if self._turns.get(session_id) is not turn:
                return turn.terminal_result or "provider"
            if turn.terminal_result is None:
                turn.terminal_result = (
                    "interrupted" if turn.stop_requested else "provider"
                )
            return turn.terminal_result

    def release(self, session_id: str, turn: _ActiveTurn) -> None:
        with self._lock:
            if self._turns.get(session_id) is turn:
                del self._turns[session_id]

    def contains(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._turns


class _BoundAgentAdapter:
    """Pin a legacy route's Provider preset without adding a Session mode."""

    def __init__(self, delegate: ProviderAdapter, agent: str | None) -> None:
        self.delegate = delegate
        self.agent = agent
        self.provider_id = delegate.provider_id
        self.capabilities = delegate.capabilities
        self.completion_on_clean_eof = delegate.completion_on_clean_eof

    def start_turn(
        self,
        message: str,
        *,
        model: str | None = None,
        agent: str | None = None,
    ) -> ProviderTurn:
        return self.delegate.start_turn(
            message,
            model=model,
            agent=self.agent,
        )

    def resume_turn(
        self,
        native_session_id: str,
        message: str,
        *,
        model: str | None = None,
        agent: str | None = None,
    ) -> ProviderTurn:
        return self.delegate.resume_turn(
            native_session_id,
            message,
            model=model,
            agent=self.agent,
        )



def create_app(
    layout: ProjectLayout | None = None,
    *,
    opencode_runner: CommandRunner | None = None,
    opencode_stream_runner: StreamRunner | None = None,
    registry: Registry = DEFAULT_REGISTRY,
) -> FastAPI:
    if layout is None:
        layout = ProjectLayout.require()

    # §13.6: agent write power only enters through this server, so activating
    # the embedded checkpoint repo here guarantees every kernel commit from
    # now on has a git recovery point. Best-effort — a machine without git
    # can still browse the graph.
    try:
        ensure_repo(layout)
    except (OSError, subprocess.CalledProcessError) as exc:
        logging.getLogger(__name__).warning(
            "checkpoint repo init failed (no recovery net): %s", exc
        )

    recover_orphaned_sessions(layout)
    app = FastAPI(title="Simulanka Graph API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEV_ORIGINS),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )
    active_turns = _ActiveTurnRegistry()
    action_resolver = ActionResolver(
        registry,
        supported_executors={
            "graph.rename_node": "GraphCommand",
            "graph.delete_node": "GraphCommand",
        },
    )

    @app.get("/registry")
    def get_registry_descriptor() -> dict[str, Any]:
        """Return the immutable semantic descriptor used by this server."""
        return registry.descriptor()

    @app.get("/graph")
    def get_graph(root: str | None = Query(default=None)) -> dict[str, Any]:
        return _build_payload(
            layout,
            root,
            registry=registry,
            action_resolver=action_resolver,
        )

    @app.get("/events")
    async def get_events(request: Request) -> StreamingResponse:
        return StreamingResponse(
            _event_stream(layout, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable proxy buffering
            },
        )

    @app.get("/ui/positions")
    def get_positions() -> dict[str, dict[str, list[float]]]:
        return _load_positions(layout)

    @app.post("/ui/positions/{root_key}")
    def post_positions(
        root_key: str,
        body: dict[str, list[float]] = Body(default_factory=dict),
    ) -> dict[str, str]:
        # Validate shape: each value must be [x, y] of finite numbers. Reject
        # everything in one shot so a malformed payload doesn't half-update.
        cleaned: dict[str, list[float]] = {}
        for node_id, xy in body.items():
            if (
                not isinstance(node_id, str)
                or not isinstance(xy, list)
                or len(xy) != 2
                or not all(isinstance(v, (int, float)) for v in xy)
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"position for {node_id!r} must be [x, y] of numbers",
                )
            cleaned[node_id] = [float(xy[0]), float(xy[1])]

        existing = _load_positions(layout)
        bucket = existing.setdefault(root_key, {})
        bucket.update(cleaned)
        _save_positions(layout, existing)
        return {"status": "ok"}

    # --- custom node templates (add-node menu, UI state like positions) ----

    @app.get("/ui/templates")
    def get_templates() -> dict[str, dict[str, Any]]:
        return _load_templates(layout)

    @app.post("/ui/templates")
    def post_template(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, str]:
        """Save (or overwrite) one custom node template.

        Body: ``{name, type, category?, attrs?, ports?}``. Templates are UI
        state, not graph entities — the graph records only what was actually
        placed. Keyed by name, so re-saving updates in place.
        """
        name = body.get("name")
        node_type = body.get("type")
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=422, detail="name is required")
        if not isinstance(node_type, str) or not node_type.strip():
            raise HTTPException(status_code=422, detail="type is required")
        category = body.get("category")
        attrs = body.get("attrs") or {}
        if not isinstance(attrs, dict):
            raise HTTPException(status_code=422, detail="attrs must be an object")
        templates = _load_templates(layout)
        templates[name.strip()] = {
            "category": category.strip()
            if isinstance(category, str) and category.strip()
            else "custom",
            "type": node_type.strip(),
            "attrs": attrs,
            "ports": _parse_ports(body.get("ports")),
        }
        _save_templates(layout, templates)
        return {"status": "ok"}

    @app.delete("/ui/templates/{name}")
    def delete_template(name: str) -> dict[str, str]:
        templates = _load_templates(layout)
        if name not in templates:
            raise HTTPException(status_code=404, detail=f"template {name!r} not found")
        del templates[name]
        _save_templates(layout, templates)
        return {"status": "ok"}

    @app.post("/edge")
    def create_edge(
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        """Persist a user-drawn ``data_flow`` edge (§13.5.2).

        Body: ``{src_port, dst_port, shape_check?}`` where the port fields are
        port ids (valid edge selectors). The edge is stamped ``source="user"``;
        ``shape_check`` (the frontend's draw-time verdict — match / mismatch /
        unknown) is recorded so the human's confirmed intent ("yes, there's a
        reshape here") survives. The kernel's out→in direction check is the only
        hard gate; a violation surfaces as 422.
        """
        src_port = body.get("src_port")
        dst_port = body.get("dst_port")
        if not isinstance(src_port, str) or not isinstance(dst_port, str):
            raise HTTPException(
                status_code=422,
                detail="src_port and dst_port (port ids) are required",
            )
        attrs: dict[str, Any] = {"source": "user"}
        shape_check = body.get("shape_check")
        if shape_check in ("match", "mismatch", "unknown"):
            attrs["shape_check"] = shape_check
        try:
            receipt = apply_patch_now(
                layout,
                ops=[CreateEdgeOp(
                    type="data_flow", source=src_port, target=dst_port, attrs=attrs,
                )],
                actor="user",
                note="frontend: draw edge",
                registry=registry,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"edge_id": receipt.edges[0], "graph_version": receipt.graph_version}

    @app.delete("/edge/{edge_id}")
    def delete_edge(edge_id: str) -> dict[str, Any]:
        """Remove an edge by id (§13.5.2 disconnect). 422 if it doesn't exist or
        is a structural ``contains`` edge the kernel refuses to drop."""
        try:
            receipt = apply_patch_now(
                layout,
                ops=[DeleteEdgeOp(edge=edge_id)],
                actor="user",
                note="frontend: remove edge",
                registry=registry,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "deleted": receipt.deleted_edges,
            "graph_version": receipt.graph_version,
        }

    # --- canvas authoring: add / rename nodes -------------------------------

    @app.post("/node")
    def create_node(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        """Create a node (plus its ports) from the canvas add-node menu.

        Body: ``{type, name, parent?, attrs?, ports?}`` with ports as
        ``[{name, direction, port_type?}]``. ``parent`` is the container the
        user is standing in (None = top-level), so a node lands where it was
        summoned. A sibling name collision gets a numeric suffix instead of a
        422 — dropping three Conv2d from the menu must just work. Ports go in
        a second patch: the disk resolver can't see pending nodes by design,
        and the importer commits node-then-ports the same way.
        """
        node_type = body.get("type")
        name = body.get("name")
        if not isinstance(node_type, str) or not node_type.strip():
            raise HTTPException(status_code=422, detail="type is required")
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=422, detail="name is required")
        parent = body.get("parent")
        if parent is not None and not isinstance(parent, str):
            raise HTTPException(status_code=422, detail="parent must be a node id")
        attrs = body.get("attrs") or {}
        if not isinstance(attrs, dict):
            raise HTTPException(status_code=422, detail="attrs must be an object")
        ports = _parse_ports(body.get("ports"))

        nodes_by_id = {n.id: n for n in iter_nodes(layout)}
        if parent is not None and parent not in nodes_by_id:
            raise HTTPException(status_code=404, detail=f"parent {parent!r} not found")
        siblings = {n.name for n in nodes_by_id.values() if n.parent_id == parent}
        base = name.strip()
        final = base
        suffix = 2
        while final in siblings:
            final = f"{base}_{suffix}"
            suffix += 1

        try:
            receipt = apply_patch_now(
                layout,
                ops=[CreateNodeOp(type=node_type.strip(), name=final, parent=parent, attrs=attrs)],
                actor="user",
                note=f"frontend: add node {final}",
                registry=registry,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        node_id = receipt.nodes[0]

        port_ids: list[str] = []
        if ports:
            try:
                receipt = apply_patch_now(
                    layout,
                    ops=[
                        CreatePortOp(
                            node=node_id,
                            name=p["name"],
                            direction=p["direction"],
                            port_type=p["port_type"],
                        )
                        for p in ports
                    ],
                    actor="user",
                    note=f"frontend: ports for {final}",
                    registry=registry,
                )
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            port_ids = receipt.ports

        return {
            "node_id": node_id,
            "name": final,
            "port_ids": port_ids,
            "graph_version": receipt.graph_version,
        }

    @app.post("/node/{node_id}/rename")
    def rename_node(
        node_id: str,
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        """Rename a node whose Profile exposes the structural capability.

        Domain packages with source-bound names (for example FileRegistry
        nodes) omit that capability. Sibling conflicts remain the kernel's
        state-policy 422.
        """
        new_name = body.get("new_name")
        if not isinstance(new_name, str) or not new_name.strip():
            raise HTTPException(status_code=422, detail="new_name is required")
        node = next((n for n in iter_nodes(layout) if n.id == node_id), None)
        if node is None:
            raise HTTPException(status_code=404, detail=f"node {node_id!r} not found")
        _require_action(
            action_resolver,
            "node.rename",
            _node_action_target(node, registry),
            actor="user",
        )
        try:
            receipt = apply_patch_now(
                layout,
                ops=[RenameNodeOp(target=node_id, new_name=new_name.strip())],
                actor="user",
                note=f"frontend: rename {node.name} → {new_name.strip()}",
                registry=registry,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"node_id": node_id, "graph_version": receipt.graph_version}

    @app.delete("/node/{node_id}")
    def delete_node_endpoint(node_id: str) -> dict[str, Any]:
        """Delete an empty node whose Profile exposes ``deletable``.

        Capability selects structural candidates; the kernel still enforces
        current graph state (children, incident structure, and integrity).
        """
        node = next((n for n in iter_nodes(layout) if n.id == node_id), None)
        if node is None:
            raise HTTPException(status_code=404, detail=f"node {node_id!r} not found")
        _require_action(
            action_resolver,
            "node.delete",
            _node_action_target(node, registry),
            actor="user",
        )
        try:
            receipt = apply_patch_now(
                layout,
                ops=[DeleteNodeOp(node=node_id)],
                actor="user",
                note=f"frontend: delete node {node.name}",
                registry=registry,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "deleted": receipt.deleted_nodes,
            "deleted_edges": receipt.deleted_edges,
            "graph_version": receipt.graph_version,
        }

    @app.get("/node/{node_id}")
    def get_node_info(node_id: str) -> dict[str, Any]:
        """Slim locator — the jump-and-select primitive's server half: to
        select an entity the canvas must first open its parent's view."""
        try:
            node = load_node(layout, node_id)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"node {node_id!r} not found"
            ) from None
        return {
            "id": node.id,
            "type": node.type,
            "name": node.name,
            "parent_id": node.parent_id,
        }

    @app.get("/node/{node_id}/provenance")
    def get_provenance(node_id: str) -> dict[str, Any]:
        """S6 血缘链: fixed-edge-set backtrack from a research atom to its
        plan file, node and edge trust levelled separately per hop. Computed
        at query time, never persisted."""
        try:
            chain = provenance_chain(layout, node_id, registry=registry)
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"node {node_id!r} not found"
            ) from None
        return {"chain": chain}

    @app.post("/node/{node_id}/resolve")
    def resolve_note_endpoint(
        node_id: str,
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        """S7: the in-place 「已处理」 act on an escalate note. Only this
        explicit human act clears a stop signal (``status→resolved``,
        ``actor=user``) — a later plan ingest never auto-mutes it. Body:
        ``{resolve_note?}``. Non-escalate targets are the wrapped 422."""
        raw = body.get("resolve_note")
        if raw is not None and not isinstance(raw, str):
            raise HTTPException(status_code=422, detail="resolve_note must be a string")
        note = raw.strip() if isinstance(raw, str) and raw.strip() else None
        try:
            node = resolve_escalate(layout, node_id, resolve_note=note)
        except PlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "node_id": node.id,
            "status": node.attrs.get("status"),
            "graph_version": load_manifest(layout).graph_version,
        }

    # --- §13.6 verify-discuss: human-side edge ops -------------------------
    # All four are thin UpdateAttrsOp wrappers; the kernel stays the only
    # writer. They cover the human (intent-domain) cells of the write matrix —
    # the agent's op-block channel is the Codex harness seam, not here.

    @app.post("/edge/{edge_id}/verdict")
    def post_verdict(
        edge_id: str,
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        """Human verdict on a ``data_flow`` edge (§13.6 分歧提交).

        Body: ``{verdict, note}``. ``verdict`` is the user-writable subset —
        ``wrong`` (reject a ghost / own edge), ``disputed`` (insist against
        the agent's verdict on a human-drawn edge), ``correct`` (post-
        discussion confirmation). ``note`` is **required**: defending the
        judgment is the learning moment (Q4), and it gives the agent a
        concrete claim to argue with. Rejecting a ghost does NOT delete it —
        ``status`` stays ``proposed`` so it enters the disagreement queue;
        deletion happens only after discussion via DELETE /edge/{id}.
        """
        _require_data_flow(layout, edge_id)
        verdict = body.get("verdict")
        note = body.get("note")
        if verdict not in ("correct", "wrong", "disputed"):
            raise HTTPException(
                status_code=422,
                detail="verdict must be one of: correct, wrong, disputed",
            )
        if not isinstance(note, str) or not note.strip():
            raise HTTPException(
                status_code=422,
                detail="note is required — defend the judgment (我认为…因为…)",
            )
        receipt = _apply_user_op(
            layout,
            UpdateAttrsOp(
                target=edge_id,
                attrs={
                    "verdict": verdict,
                    "verdict_by": "user",
                    "verdict_note": note.strip(),
                },
            ),
            note="frontend: human verdict",
            registry=registry,
        )
        return {"edge_id": edge_id, "graph_version": receipt.graph_version}

    @app.post("/edge/{edge_id}/accept")
    def accept_ghost(edge_id: str) -> dict[str, Any]:
        """Accept a proposed ghost edge (§13.5.3 同意即连). Agreement needs no
        defense, so no note. Only the human may do this (write matrix)."""
        edge = _require_data_flow(layout, edge_id)
        if not (
            edge.attrs.get("source") == "agent"
            and edge.attrs.get("status") == "proposed"
        ):
            raise HTTPException(
                status_code=422,
                detail="only a proposed ghost edge can be accepted",
            )
        receipt = _apply_user_op(
            layout,
            UpdateAttrsOp(
                target=edge_id,
                attrs={
                    "status": "accepted",
                    "verdict": "correct",
                    "verdict_by": "user",
                },
            ),
            note="frontend: accept ghost",
            registry=registry,
        )
        return {"edge_id": edge_id, "graph_version": receipt.graph_version}

    @app.post("/edge/{edge_id}/discuss")
    def set_discuss(
        edge_id: str,
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        """Pull any edge into (or out of) the discussion set by hand.
        Body: ``{discuss: bool}``, defaults to true."""
        _require_data_flow(layout, edge_id)
        flag = body.get("discuss", True)
        if not isinstance(flag, bool):
            raise HTTPException(status_code=422, detail="discuss must be a boolean")
        receipt = _apply_user_op(
            layout,
            UpdateAttrsOp(target=edge_id, attrs={"discuss": flag}),
            note="frontend: toggle discuss",
            registry=registry,
        )
        return {"edge_id": edge_id, "graph_version": receipt.graph_version}

    @app.get("/file/content")
    def get_file_content(
        node: str | None = Query(default=None),
        path: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Read a registered file node's content (S4 universal file viewer).

        Exactly one of ``node`` (file node id) or ``path`` (project-relative
        ``fs_path``, as stamped in attrs like ``plan_file``) selects the file.
        The graph stays the authority on what is readable: an unregistered
        path 404s even if it exists on disk. Binary and over-cap files are
        reported honestly rather than mangled.
        """
        if (node is None) == (path is None):
            raise HTTPException(
                status_code=422, detail="pass exactly one of `node` / `path`",
            )
        if node is not None:
            try:
                file_node = load_node(layout, node)
            except FileNotFoundError:
                raise HTTPException(
                    status_code=404, detail=f"no node {node!r}",
                ) from None
            if file_node.type != "file":
                raise HTTPException(
                    status_code=422,
                    detail=f"node {node!r} is `{file_node.type}`, not `file`",
                )
        else:
            found = next(
                (
                    n for n in iter_nodes(layout)
                    if n.type == "file" and n.attrs.get("fs_path") == path
                ),
                None,
            )
            if found is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"no registered file node with fs_path {path!r}",
                )
            file_node = found

        fs_path = file_node.attrs.get("fs_path")
        if not isinstance(fs_path, str):
            raise HTTPException(
                status_code=404,
                detail=f"file node {file_node.id} has no fs_path attr",
            )
        abs_path = layout.root / fs_path
        if not abs_path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"`{fs_path}` is not a regular file on disk",
            )

        size = abs_path.stat().st_size
        with abs_path.open("rb") as f:
            data = f.read(FILE_CONTENT_CAP)
        binary = b"\x00" in data
        return {
            "id": file_node.id,
            "name": file_node.name,
            "kind": file_node.attrs.get("kind"),
            "fs_path": fs_path,
            "size_bytes": size,
            "binary": binary,
            "truncated": size > len(data),
            "content": None if binary else data.decode("utf-8", errors="replace"),
        }

    @app.get("/disagreements")
    def get_disagreements() -> dict[str, Any]:
        """The §13.6 disagreement set, computed from edge attrs (no extra
        state): ① ghosts the human rejected, ② human-drawn edges the agent's
        verify pass ruled wrong/uncertain, ③ disputed verdicts, ④ edges pulled
        in by hand. One edge can match several buckets — ``reasons`` lists all.
        """
        return {"disagreements": disagreement_list(layout)}

    # --- S8 provider-neutral sessions --------------------------------------

    def message_context_bundles(body: dict[str, Any]) -> tuple[ContextBundle, ...]:
        raw_refs = body.get("refs", [])
        if not isinstance(raw_refs, list):
            raise HTTPException(status_code=422, detail="refs must be a list")
        refs: list[ContextRef] = []
        for raw_ref in raw_refs:
            if not isinstance(raw_ref, dict) or set(raw_ref) != {"kind", "ref_id"}:
                raise HTTPException(
                    status_code=422,
                    detail="each ref must contain exactly kind and ref_id",
                )
            kind = raw_ref.get("kind")
            ref_id = raw_ref.get("ref_id")
            if not isinstance(kind, str) or not isinstance(ref_id, str):
                raise HTTPException(
                    status_code=422,
                    detail="ref kind and ref_id must be strings",
                )
            try:
                refs.append(ContextRef(kind, ref_id))  # type: ignore[arg-type]
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not refs:
            return ()

        expected_graph_version = body.get("expected_graph_version")
        if expected_graph_version is not None and type(expected_graph_version) is not int:
            raise HTTPException(
                status_code=422,
                detail="expected_graph_version must be an integer",
            )
        missing = body.get("missing", "error")
        if not isinstance(missing, str):
            raise HTTPException(status_code=422, detail="missing must be error or omit")
        try:
            bundle = compile_context(
                layout,
                RefSet(tuple(refs)),
                missing=missing,  # type: ignore[arg-type]
                expected_graph_version=expected_graph_version,
            )
        except ContextSnapshotError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ContextReferenceError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return (bundle,)

    def session_stream_response(
        state: Session,
        text: str,
        bundles: tuple[ContextBundle, ...],
        *,
        include_created: bool,
    ) -> StreamingResponse:
        session_id = state.session_id
        adapter = provider_adapters.create(
            state.provider_id,
            runner=opencode_stream_runner,
            workspace=state.workspace,
        )
        turn = active_turns.reserve(session_id, adapter.capabilities)
        if turn is None or state.turn_running:
            if turn is not None:
                active_turns.release(session_id, turn)
            raise HTTPException(
                status_code=409,
                detail="a turn is already running for this session",
            )

        def event_stream() -> Iterator[str]:
            try:
                if include_created:
                    created = read_session_events(layout, session_id)[0]
                    yield json.dumps(created, ensure_ascii=False) + "\n"
                yield from stream_session_turn(
                    layout,
                    state,
                    text,
                    bundles=bundles,
                    adapter=adapter,
                    on_turn_handle=lambda handle: active_turns.bind(
                        session_id,
                        turn,
                        handle,
                    ),
                    claim_terminal=lambda: active_turns.claim_terminal(
                        session_id,
                        turn,
                    ),
                )
            finally:
                active_turns.release(session_id, turn)

        return StreamingResponse(
            event_stream(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Simulanka-Session-Id": session_id,
            },
        )

    def bound_session_record(state: Session) -> dict[str, Any]:
        states = list_sessions(layout)
        if all(candidate.session_id != state.session_id for candidate in states):
            states.append(state)
        binding = session_tree_bindings(layout, states)[state.session_id]
        return session_record(state, binding)

    @app.post("/session")
    def create_agent_session(
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> StreamingResponse:
        allowed = {
            "text",
            "provider_id",
            "model",
            "scope_root_id",
            "refs",
            "expected_graph_version",
            "missing",
        }
        unknown = set(body) - allowed
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown session fields: {sorted(unknown)}",
            )
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=422, detail="text is required")
        provider_id = body.get("provider_id")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise HTTPException(
                status_code=422,
                detail="provider_id must be a non-empty string",
            )
        provider_id = provider_id.strip()
        model = body.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise HTTPException(status_code=422, detail="model must be a string")
        scope_root_id = body.get("scope_root_id")
        if scope_root_id is not None and (
            not isinstance(scope_root_id, str) or not scope_root_id.strip()
        ):
            raise HTTPException(
                status_code=422,
                detail="scope_root_id must be a node id or null",
            )
        if isinstance(scope_root_id, str):
            scope_root_id = scope_root_id.strip()
            if not node_exists(layout, scope_root_id):
                raise HTTPException(
                    status_code=422,
                    detail=f"scope_root_id {scope_root_id!r} does not exist",
                )
        bundles = message_context_bundles(body)
        try:
            provider_adapters.create(
                provider_id,
                runner=opencode_stream_runner,
                workspace=str(layout.root),
            )
        except HarnessError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        state = create_session(
            layout,
            provider_id=provider_id,
            model=model.strip() if isinstance(model, str) else None,
            workspace=layout.root,
            scope_root_id=(
                scope_root_id if isinstance(scope_root_id, str) else None
            ),
        )
        return session_stream_response(
            state,
            text,
            bundles,
            include_created=True,
        )

    @app.get("/session")
    def agent_session_list(scope: str | None = None) -> dict[str, Any]:
        states = list_sessions(layout)
        bindings = session_tree_bindings(layout, states)
        records = [
            session_record(state, bindings[state.session_id])
            for state in states
        ]
        if scope == "top":
            records = [
                record
                for record in records
                if record["scope_status"] == "bound"
                and record["scope_root_id"] is None
            ]
        elif scope == "unassigned":
            records = [
                record
                for record in records
                if record["scope_status"] in {"unassigned", "missing", "broken"}
            ]
        elif scope is not None:
            records = [
                record
                for record in records
                if record["scope_status"] == "bound"
                and record["scope_root_id"] == scope
            ]
        return {"sessions": records}

    @app.get("/session/providers")
    def agent_session_providers() -> dict[str, Any]:
        return {
            "providers": [
                {
                    "provider_id": provider_id,
                    "capabilities": asdict(capabilities),
                }
                for provider_id, capabilities in provider_adapters.capabilities().items()
            ]
        }

    @app.get("/session/{session_id}/history")
    def agent_session_history(session_id: str) -> dict[str, Any]:
        try:
            state = load_session(layout, session_id)
            events = read_session_events(layout, session_id)
        except SessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SessionStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "session_id": session_id,
            "session": bound_session_record(state),
            "events": events,
        }

    @app.post("/session/{session_id}/fork")
    def agent_session_fork(
        session_id: str,
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        allowed = {"provider_id", "model", "forked_from_event_id"}
        unknown = set(body) - allowed
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown fork fields: {sorted(unknown)}",
            )
        provider_id = body.get("provider_id")
        if provider_id is not None and (
            not isinstance(provider_id, str) or not provider_id.strip()
        ):
            raise HTTPException(
                status_code=422,
                detail="provider_id must be a non-empty string",
            )
        model = body.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise HTTPException(
                status_code=422,
                detail="model must be a string or null",
            )
        forked_from_event_id = body.get("forked_from_event_id")
        if forked_from_event_id is not None and (
            not isinstance(forked_from_event_id, str)
            or not forked_from_event_id.strip()
        ):
            raise HTTPException(
                status_code=422,
                detail="forked_from_event_id must be a non-empty string",
            )
        try:
            parent = load_session(layout, session_id)
            resolved_provider_id = (
                parent.provider_id
                if provider_id is None
                else provider_id.strip()
            )
            provider_adapters.create(
                resolved_provider_id,
                runner=opencode_stream_runner,
                workspace=parent.workspace,
            )
            child = fork_session(
                layout,
                session_id,
                provider_id=resolved_provider_id,
                model=model.strip() if isinstance(model, str) else None,
                inherit_model="model" not in body,
                forked_from_event_id=(
                    forked_from_event_id.strip()
                    if isinstance(forked_from_event_id, str)
                    else None
                ),
            )
        except SessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SessionStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except HarnessError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return bound_session_record(child)

    @app.post("/session/{session_id}/archive")
    def agent_session_archive(
        session_id: str,
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        if body:
            raise HTTPException(
                status_code=422,
                detail=f"unknown archive fields: {sorted(body)}",
            )
        if active_turns.contains(session_id):
            raise HTTPException(
                status_code=409,
                detail="cannot archive a running session",
            )
        try:
            state = archive_session(layout, session_id)
        except SessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SessionStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return bound_session_record(state)

    @app.post("/session/{session_id}/stop")
    def agent_session_stop(
        session_id: str,
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, str]:
        if body:
            raise HTTPException(
                status_code=422,
                detail=f"unknown stop fields: {sorted(body)}",
            )
        try:
            state = load_session(layout, session_id)
        except SessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        capabilities = provider_adapters.create(state.provider_id).capabilities
        if capabilities.native_resume and state.native_session_id is None:
            raise HTTPException(
                status_code=409,
                detail="native session id is not available yet; retry shortly",
            )
        result = active_turns.request_stop(session_id)
        if result == "unsupported":
            raise HTTPException(
                status_code=409,
                detail="the active provider does not support interruption",
            )
        if result in {"missing", "finished"}:
            raise HTTPException(
                status_code=409,
                detail="no interruptible turn is running for this session",
            )
        return {"status": result}

    @app.post("/session/context/preview")
    def preview_context(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Compile explicit references and read their incremental delivery state."""
        allowed = {"refs", "session_id", "expected_graph_version", "missing"}
        unknown = set(body) - allowed
        if unknown:
            raise HTTPException(
                status_code=422, detail=f"unknown preview fields: {sorted(unknown)}"
            )
        raw_refs = body.get("refs")
        if not isinstance(raw_refs, list):
            raise HTTPException(status_code=422, detail="refs must be a list")
        refs: list[ContextRef] = []
        for raw_ref in raw_refs:
            if not isinstance(raw_ref, dict) or set(raw_ref) != {"kind", "ref_id"}:
                raise HTTPException(
                    status_code=422,
                    detail="each ref must contain exactly kind and ref_id",
                )
            kind = raw_ref.get("kind")
            ref_id = raw_ref.get("ref_id")
            if not isinstance(kind, str) or not isinstance(ref_id, str):
                raise HTTPException(status_code=422, detail="ref kind and ref_id must be strings")
            try:
                refs.append(ContextRef(kind, ref_id))  # type: ignore[arg-type]
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        session_id = body.get("session_id")
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            raise HTTPException(status_code=422, detail="session_id must be a non-empty string")
        expected_graph_version = body.get("expected_graph_version")
        if expected_graph_version is not None and type(expected_graph_version) is not int:
            raise HTTPException(status_code=422, detail="expected_graph_version must be an integer")
        missing = body.get("missing", "error")
        if not isinstance(missing, str):
            raise HTTPException(status_code=422, detail="missing must be error or omit")

        try:
            bundle = compile_context(
                layout,
                RefSet(tuple(refs)),
                missing=missing,  # type: ignore[arg-type]
                expected_graph_version=expected_graph_version,
            )
        except ContextSnapshotError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ContextReferenceError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        session = None
        if session_id is not None:
            try:
                session = load_session(layout, session_id)
            except SessionNotFound as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

        payload = bundle.payload_object()
        if not refs:
            action, reason = "skip", "no_supplement"
            bundle_record: dict[str, Any] | None = None
        elif not payload["reference"]:
            action, reason = "skip", "no_resolved_content"
            bundle_record = bundle.as_record()
        elif session is None:
            action, reason = "send", "new_session"
            bundle_record = bundle.as_record()
        elif session.native_session_id is None:
            action, reason = "send", "native_session_pending"
            bundle_record = bundle.as_record()
        else:
            decision = decide_context_delivery(layout, session.native_session_id, bundle)
            action = decision.action
            reason = "already_sent" if action == "skip" else "new_digest"
            bundle_record = bundle.as_record()
        return {
            "bundle": bundle_record,
            "payload": payload,
            "sources": [reference["source"] for reference in payload["reference"]],
            "omissions": [omission.as_dict() for omission in bundle.omissions],
            "delivery": {"action": action, "reason": reason},
        }

    @app.post("/session/{session_id}/message")
    def agent_session_message(
        session_id: str,
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> StreamingResponse:
        allowed = {"text", "refs", "expected_graph_version", "missing"}
        unknown = set(body) - allowed
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown message fields: {sorted(unknown)}",
            )
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=422, detail="text is required")
        bundles = message_context_bundles(body)
        try:
            state = load_session(layout, session_id)
        except SessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if state.status == "archived":
            raise HTTPException(
                status_code=409,
                detail="archived sessions are read-only; fork or create a new session",
            )
        return session_stream_response(
            state,
            text,
            bundles,
            include_created=False,
        )

    # --- §13.6 legacy discussion compatibility -----------------------------
    # These routes retain their old response and write-matrix contract, but
    # Session JSONL is now their sole transcript and lifecycle store.

    legacy_stream_runner = opencode_stream_runner
    if opencode_runner is not None:

        def command_runner_stream(
            args: list[str],
            _env: Mapping[str, str],
        ) -> Iterable[str]:
            return opencode_runner(args, DEFAULT_TIMEOUT).splitlines()

        legacy_stream_runner = command_runner_stream

    def _run_discussion_turn(
        state: Session,
        message: str,
        *,
        agent: str | None = None,
    ) -> tuple[Session, str, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        adapter = _BoundAgentAdapter(
            provider_adapters.create(
                state.provider_id,
                runner=legacy_stream_runner,
                workspace=state.workspace,
            ),
            agent,
        )
        active = active_turns.reserve(state.session_id, adapter.capabilities)
        if active is None or state.turn_running:
            if active is not None:
                active_turns.release(state.session_id, active)
            raise HTTPException(
                status_code=409,
                detail="a turn is already running for this session",
            )

        events: list[dict[str, Any]] = []
        try:
            for line in stream_session_turn(
                layout,
                state,
                message,
                adapter=adapter,
                on_turn_handle=lambda handle: active_turns.bind(
                    state.session_id,
                    active,
                    handle,
                ),
                claim_terminal=lambda: active_turns.claim_terminal(
                    state.session_id,
                    active,
                ),
            ):
                event = json.loads(line)
                if isinstance(event, dict):
                    events.append(event)
        finally:
            active_turns.release(state.session_id, active)

        current = load_session(layout, state.session_id)
        if current.status != "done":
            error_text = next(
                (
                    event["text"]
                    for event in reversed(events)
                    if event.get("type") == "error"
                    and isinstance(event.get("text"), str)
                ),
                f"discussion compatibility turn ended as {current.status}",
            )
            raise HTTPException(status_code=502, detail=error_text)

        reply = "\n".join(
            event["text"]
            for event in events
            if event.get("type") == "agent_text"
            and isinstance(event.get("text"), str)
        ).strip()
        parsed = parse_op_blocks(reply)
        applied, rejected = apply_agent_ops(layout, parsed.ops, registry=registry)
        return current, reply, applied, rejected, parsed.errors

    @app.post("/discussion/start")
    def discussion_start(
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        """Open the batch discussion. Body: ``{model?}``."""
        model = body.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise HTTPException(status_code=422, detail="model must be a string")
        # 会话是语言原语（2026-07-14）：没有分歧也能开。空批次走通用图助手
        # 开场；分歧批次只是骑在同一会话机制上的一个用法（§13.6 一批一场、
        # 写权闸、checkpoint 全部不变）。
        disagreements = disagreement_list(layout)
        # §13.6 撤回兜底: the round start is the recovery target. Best-effort,
        # same as per-commit checkpoints — a broken git must not block talk.
        if repo_exists(layout):
            try:
                tag_checkpoint(layout, "discussion-start")
            except (OSError, subprocess.CalledProcessError) as exc:
                logging.getLogger(__name__).warning(
                    "discussion-start tag failed: %s", exc
                )
        # Batch-less canvas chat rides the repo's tool-less `graph-chat` agent
        # (.opencode/agent/) — the default `build` agent starts running tools
        # against the codebase and a turn takes minutes (彩排实测=「卡死」).
        # The batch (verify) flow keeps the default agent: citations need code
        # access. The choice is per-session and sticks via state.
        agent = None if disagreements else "graph-chat"
        opening = (
            _opening_message(disagreements) if disagreements else GENERAL_OPENING
        )
        state = create_session(
            layout,
            provider_id="opencode",
            model=model.strip() if isinstance(model, str) else None,
            workspace=layout.root,
            scope_root_id=None,
        )
        current, reply, applied, rejected, op_errors = _run_discussion_turn(
            state,
            opening,
            agent=agent,
        )
        assert current.native_session_id is not None
        pointer = {
            "platform_session_id": current.session_id,
            "model": model,
            "agent": agent,
            "batch": [d["id"] for d in disagreements],
        }
        _save_discussion(layout, pointer)
        return {
            "session_id": current.native_session_id,
            **pointer,
            "reply": reply,
            "applied": applied,
            "rejected": rejected,
            "op_errors": op_errors,
        }

    @app.post("/discussion/message")
    def discussion_message(
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        """One human turn in the active discussion. Body: ``{text}``."""
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=422, detail="text is required")
        pointer = _load_discussion(layout)
        if pointer is None:
            raise HTTPException(
                status_code=422,
                detail="no active discussion — POST /discussion/start first",
            )
        platform_session_id = pointer.get("platform_session_id")
        if not isinstance(platform_session_id, str):
            raise HTTPException(
                status_code=422,
                detail="legacy discussion pointer cannot be resumed; start a new session",
            )
        try:
            state = load_session(layout, platform_session_id)
        except (SessionNotFound, SessionStateError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if state.status == "archived":
            raise HTTPException(
                status_code=409,
                detail="archived sessions are read-only; fork or create a new session",
            )
        current, reply, applied, rejected, op_errors = _run_discussion_turn(
            state,
            text,
            agent=pointer.get("agent") if isinstance(pointer.get("agent"), str) else None,
        )
        assert current.native_session_id is not None
        return {
            "session_id": current.native_session_id,
            "platform_session_id": current.session_id,
            "reply": reply,
            "applied": applied,
            "rejected": rejected,
            "op_errors": op_errors,
        }

    @app.get("/discussion")
    def discussion_state() -> dict[str, Any]:
        pointer = _load_discussion(layout)
        if pointer is None:
            return {"active": False}
        platform_session_id = pointer.get("platform_session_id")
        if not isinstance(platform_session_id, str):
            return {"active": False}
        try:
            state = load_session(layout, platform_session_id)
        except (SessionNotFound, SessionStateError):
            return {"active": False}
        return {
            "active": state.status != "archived",
            "session_id": state.native_session_id,
            "platform_session_id": state.session_id,
            "model": state.model,
            "agent": pointer.get("agent"),
            "batch": pointer.get("batch", []),
            "status": state.status,
        }

    return app


def _require_data_flow(layout: ProjectLayout, edge_id: str) -> Edge:
    """404 on unknown edge, 422 on a non-``data_flow`` edge (verdicts on
    structural edges are meaningless)."""
    try:
        edge = load_edge(layout, edge_id)
    except FileNotFoundError:
        # Single read, no exists() pre-check: endpoints run concurrently in
        # the threadpool, so check-then-read would race a DELETE /edge.
        raise HTTPException(
            status_code=404, detail=f"edge {edge_id!r} not found"
        ) from None
    if edge.type != "data_flow":
        raise HTTPException(
            status_code=422,
            detail="verify-discuss ops apply to data_flow edges only",
        )
    return edge


def _node_action_target(
    node: Node,
    registry: Registry,
) -> ActionTarget:
    return _entity_action_target(
        registry,
        kind="node",
        entity_id=node.id,
        profile=node.type,
        attrs=node.attrs,
    )


def _entity_action_target(
    registry: Registry,
    *,
    kind: Literal["node", "edge", "port"],
    entity_id: str,
    profile: str,
    attrs: Mapping[str, Any],
) -> ActionTarget:
    raw_source = attrs.get("source")
    source = raw_source if isinstance(raw_source, str) else "graph"
    projected_immutable = source == "projection" and attrs.get("immutable") is True
    raw_lock_reason = attrs.get("lock_reason")
    lock_reason = (
        raw_lock_reason
        if isinstance(raw_lock_reason, str) and raw_lock_reason
        else "实体当前已锁定"
    )
    return ActionTarget.from_profile(
        registry,
        kind=kind,
        id=entity_id,
        profile=profile,
        source=source,
        writable=not projected_immutable,
        locked=attrs.get("locked") is True,
        lock_reason=lock_reason,
    )


def _require_action(
    resolver: ActionResolver,
    action_id: str,
    target: ActionTarget,
    *,
    actor: str,
) -> None:
    affordance = resolver.resolve_action(action_id, (target,), actor=actor)
    if not affordance.enabled:
        raise HTTPException(
            status_code=422,
            detail={
                "action": affordance.id,
                "reason": affordance.reason,
                "reason_code": affordance.reason_code,
            },
        )


def _apply_user_op(
    layout: ProjectLayout,
    op: UpdateAttrsOp,
    note: str,
    *,
    registry: Registry,
) -> Receipt:
    """apply_patch_now with kernel rejections surfaced as 422 — e.g. the edge
    vanished between the endpoint's precondition check and the write."""
    try:
        return apply_patch_now(
            layout,
            ops=[op],
            actor="user",
            note=note,
            registry=registry,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _build_payload(
    layout: ProjectLayout,
    root: str | None,
    *,
    registry: Registry,
    action_resolver: ActionResolver,
) -> dict[str, Any]:
    """Return the one-container view payload: the inside of ``root``.

    The canvas mental model is a subgraph view — one view shows the direct
    children of one container, never the container itself and never deeper
    levels (drill-down navigates; it doesn't flatten). Containment comes from
    Node.parent_id (denormalised cache of `contains` edges).

    - `nodes`: direct children of root (top-level nodes when root is None).
    - `root_info`: slim {id,type,name} of the container itself, for the
      breadcrumb; None at top-level.
    - `edges`: both endpoints in the view.
    - `boundary_edges`: exactly one endpoint in the view — minus `contains`
      edges, whose nesting the view itself already renders (§12.3). Only
      filled when root is given — at top-level there is no outside. Edges
      from the root's own ports to its children land here and project as the
      subgraph's input/output brackets (§12.4).
    - `external_nodes`: slim {id,type,name} for the outside endpoints
      referenced by boundary_edges, so boundary ports can be labelled.
    - `child_count` on each node: count of direct children; the frontend uses
      it to decide whether a node is drillable.
    """
    nodes_by_id = {n.id: n for n in iter_nodes(layout)}
    if root is not None and root not in nodes_by_id:
        raise HTTPException(status_code=404, detail=f"node {root!r} not found")

    children_of: dict[str | None, list[str]] = {}
    for n in nodes_by_id.values():
        children_of.setdefault(n.parent_id, []).append(n.id)

    included = set(children_of.get(root, []))

    def _is_descendant(node_id: str, ancestor_id: str) -> bool:
        cur = nodes_by_id.get(node_id)
        while cur is not None and cur.parent_id is not None:
            if cur.parent_id == ancestor_id:
                return True
            cur = nodes_by_id.get(cur.parent_id)
        return False

    edges_payload: list[dict[str, Any]] = []
    boundary_payload: list[dict[str, Any]] = []
    external_ids: set[str] = set()
    external_port_ids: set[str] = set()
    for e in iter_edges(layout):
        src_in = e.source_id in included
        dst_in = e.target_id in included
        if src_in and dst_in:
            edges_payload.append(_edge_view_payload(e, registry, action_resolver))
        elif (src_in or dst_in) and root is not None and e.type != "contains":
            inside = e.source_id if src_in else e.target_id
            outside = e.target_id if src_in else e.source_id
            # An edge diving from an in-view node into its own descendant
            # (importer tunnel edges) is internal detail of that node — its
            # projection is the child view's bracket, not this view's
            # boundary. Same reasoning as not drawing `contains`.
            if _is_descendant(outside, inside):
                continue
            boundary_payload.append(_edge_view_payload(e, registry, action_resolver))
            external_ids.add(outside)
            outside_port = e.target_port_id if src_in else e.source_port_id
            if outside_port is not None:
                external_port_ids.add(outside_port)

    # Included nodes' ports, plus the outside ports boundary edges point at —
    # without those the frontend can't label the far end of a cross-boundary
    # edge (§12.4 boundary ports, §13.6 panel endpoints) — plus the root's own
    # ports: they are the subgraph's declared IO, rendered as the view's
    # input/output brackets even when no edge crosses yet.
    ports_of: dict[str, list[str]] = {}
    ports_payload: list[dict[str, Any]] = []
    for p in iter_ports(layout):
        if p.node_id in included:
            ports_of.setdefault(p.node_id, []).append(p.id)
        elif p.node_id != root and p.id not in external_port_ids:
            continue
        target = _entity_action_target(
            registry,
            kind="port",
            entity_id=p.id,
            profile=p.port_type,
            attrs=p.attrs,
        )
        ports_payload.append(
            {
                "id": p.id,
                "node_id": p.node_id,
                "name": p.name,
                "side": p.direction,
                "port_type": p.port_type,
                "attrs": p.attrs,
                **_action_metadata(target, action_resolver),
            }
        )

    external_payload: list[dict[str, Any]] = []
    for nid in external_ids:
        if nid not in nodes_by_id:
            continue
        node = nodes_by_id[nid]
        external_payload.append(
            {
                "id": node.id,
                "type": node.type,
                "name": node.name,
                **_action_metadata(
                    _node_action_target(node, registry),
                    action_resolver,
                ),
            }
        )

    # S6: trust is query-time-computed here and never persisted; research-
    # domain nodes get their level, everything else null. The canvas colours
    # node bodies only — edge colours keep their source/verdict semantics.
    nodes_payload: list[dict[str, Any]] = []
    for nid, node in nodes_by_id.items():
        if nid not in included:
            continue
        nodes_payload.append(
            {
                "id": node.id,
                "type": node.type,
                "name": node.name,
                "parent_id": node.parent_id,
                "attrs": node.attrs,
                "ports": ports_of.get(node.id, []),
                "child_count": len(children_of.get(node.id, [])),
                "trust": node_trust(node, registry=registry),
                **_action_metadata(
                    _node_action_target(node, registry),
                    action_resolver,
                ),
            }
        )

    # Ancestor chain from top-level down to the root's direct parent. Lets the
    # frontend reconstruct the breadcrumb trail for a non-null root regardless
    # of how the user navigated there (drill-down, jump-external, deep link).
    ancestors: list[dict[str, Any]] = []
    if root is not None:
        cur = nodes_by_id[root].parent_id
        while cur is not None and cur in nodes_by_id:
            anc = nodes_by_id[cur]
            ancestors.append(
                {
                    "id": anc.id,
                    "type": anc.type,
                    "name": anc.name,
                    **_action_metadata(
                        _node_action_target(anc, registry),
                        action_resolver,
                    ),
                }
            )
            cur = anc.parent_id
        ancestors.reverse()

    root_info: dict[str, Any] | None = None
    if root is not None:
        rn = nodes_by_id[root]
        root_info = {
            "id": rn.id,
            "type": rn.type,
            "name": rn.name,
            **_action_metadata(
                _node_action_target(rn, registry),
                action_resolver,
            ),
        }

    return {
        "registry_digest": registry.descriptor_digest,
        "root": root,
        "root_info": root_info,
        "nodes": nodes_payload,
        "edges": edges_payload,
        "boundary_edges": boundary_payload,
        "external_nodes": external_payload,
        "ports": ports_payload,
        "ancestors": ancestors,
    }


def _edge_view_payload(
    edge: Edge,
    registry: Registry,
    action_resolver: ActionResolver,
) -> dict[str, Any]:
    return {
        **edge_payload(edge),
        **_action_metadata(
            _entity_action_target(
                registry,
                kind="edge",
                entity_id=edge.id,
                profile=edge.type,
                attrs=edge.attrs,
            ),
            action_resolver,
        ),
    }


def _action_metadata(
    target: ActionTarget,
    resolver: ActionResolver,
) -> dict[str, Any]:
    return {
        "capabilities": sorted(target.capabilities),
        "unknown_profile": target.unknown_profile,
        "affordances": [
            affordance.as_dict()
            for affordance in resolver.resolve((target,), actor="user")
        ],
    }


# Batch-less opening: the chat surface is a language primitive — it must open
# without a disagreement set. Prompt *wording* is Codex's editorial territory
# (issue #2); this generic opening is a mechanical placeholder riding the same
# review.
GENERAL_OPENING = """\
You are the graph assistant of a Simulanka research project. The human chats
from the graph canvas; a message may start with an anchor tag（锚定：…）naming
the node or container they are looking at — treat it as the topic. Reply
plainly and concretely. Do not fabricate graph state you were not shown.
"""

# Prompt *wording* is Codex's editorial territory (issue #2); the server owns
# only the mechanical contract: context JSON in, simulanka-ops protocol out.
OPENING_TEMPLATE = """\
You are the verify-discuss agent on a Simulanka research graph. The human and
you disagree about the data-flow edges below. Your job is to keep the graph
honest, not to win the argument.

Disagreement set (JSON):
```json
{context}
```

First reply with a concise triage for each edge:
- edge_id
- stance: agree_with_human, disagree_with_human, or insufficient_evidence
- the specific evidence you found, or what evidence is missing

Target the human's `verdict_note` directly. If the note is right, concede. If
the evidence is mixed, preserve uncertainty instead of forcing a verdict.

You may act by embedding at most ONE fenced block labelled `simulanka-ops`,
containing {{"ops": [...]}} where each op is one of:
- {{"op": "set_verdict", "edge_id": "...",
   "attrs": {{"verdict": "correct|wrong|uncertain", "verdict_note": "..."}}}}
- {{"op": "propose_edge", "source": "<port_id>", "target": "<port_id>",
   "attrs": {{"citation": "file:line - required",
              "output_slice": "optional tensor/output slice",
              "evidence_locality": "local|cross_method|cross_state|unknown"}}}}
- {{"op": "withdraw_edge", "edge_id": "..."}}

Rules:
- You can never overwrite a human verdict; argue in prose instead.
- Citation is mandatory for `propose_edge`; no fenced op block is better than
  an uncited guess.
- Only propose edges between exact port ids from the graph context.
- Use `evidence_locality` when the evidence crosses method, module, or state
  boundaries; use `unknown` if you cannot classify it.
- You can only withdraw your own un-accepted ghost edges.

Address each disagreement, then wait for the human.
"""


def _opening_message(disagreements: list[dict[str, Any]]) -> str:
    return OPENING_TEMPLATE.format(
        context=json.dumps(disagreements, ensure_ascii=False, indent=2)
    )


def _discussion_path(layout: ProjectLayout) -> Path:
    return layout.dot_dir / "agent" / "discussion.json"


def _load_discussion(layout: ProjectLayout) -> dict[str, Any] | None:
    path = _discussion_path(layout)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    platform_session_id = data.get("platform_session_id")
    legacy_session_id = data.get("session_id")
    if not isinstance(platform_session_id, str) and not isinstance(
        legacy_session_id,
        str,
    ):
        return None
    return data


def _save_discussion(layout: ProjectLayout, state: dict[str, Any]) -> None:
    path = _discussion_path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="discussion-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _affected(event: Event) -> dict[str, list[str]]:
    """Walk canonical_ops to surface IDs the client should refresh.

    canonical_ops carry resolved entity IDs (kernel/apply.py), so no selector
    re-resolution is needed. Cross-op duplicates are de-duped while preserving
    insertion order.
    """
    nodes: dict[str, None] = {}
    edges: dict[str, None] = {}
    ports: dict[str, None] = {}
    for op in event.ops:
        kind = op.get("kind")
        eid = op.get("entity_id")
        if not isinstance(eid, str):
            continue
        if kind == "update_attrs" and eid.startswith("edg_"):
            edges[eid] = None
            for k in ("source_id", "target_id"):
                v = op.get(k)
                if isinstance(v, str):
                    nodes[v] = None
        elif kind == "create_node" or kind == "update_attrs" or kind == "rename_node":
            nodes[eid] = None
        elif kind == "create_edge" or kind == "delete_edge":
            edges[eid] = None
            for k in ("source_id", "target_id"):
                v = op.get(k)
                if isinstance(v, str):
                    nodes[v] = None
        elif kind == "delete_node":
            nodes[eid] = None
            # The parent's view is what visually changes.
            v = op.get("parent_id")
            if isinstance(v, str):
                nodes[v] = None
        elif kind == "create_port":
            ports[eid] = None
            node_id = op.get("node_id")
            if isinstance(node_id, str):
                nodes[node_id] = None
    return {
        "nodes": list(nodes),
        "edges": list(edges),
        "ports": list(ports),
    }


async def _event_stream(
    layout: ProjectLayout, request: Request
) -> AsyncIterator[bytes]:
    """SSE generator. Polls the event log every SSE_POLL_INTERVAL and yields
    one message per new event past the connection's start version. Honours
    client disconnects via Request.is_disconnected().

    The current graph_version at connect time becomes the "high water mark".
    Connecting clients should call /graph themselves to load the initial
    snapshot — /events only carries deltas after subscription.
    """
    last_seen = load_manifest(layout).graph_version
    # Heartbeat / open marker so the client knows the stream is up.
    yield _sse(
        "ready",
        {"graph_version": last_seen},
    )

    while True:
        if await request.is_disconnected():
            return
        # Iterating all segments per tick is fine at single-user scale; if event
        # volume grows we can swap in offset-based reading.
        for ev in iter_events(layout):
            if ev.graph_version <= last_seen:
                continue
            last_seen = ev.graph_version
            yield _sse(
                "commit",
                {
                    "event_id": ev.id,
                    "graph_version": ev.graph_version,
                    "actor": ev.actor,
                    **_affected(ev),
                },
            )
        await asyncio.sleep(SSE_POLL_INTERVAL)


def _sse(event_name: str, payload: dict[str, Any]) -> bytes:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n".encode()


def _positions_path(layout: ProjectLayout) -> Path:
    return layout.dot_dir / "ui" / "positions.json"


def _load_positions(layout: ProjectLayout) -> dict[str, dict[str, list[float]]]:
    path = _positions_path(layout)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        # Corrupt UI state shouldn't take down the API; pretend it's empty so
        # the next save overwrites cleanly.
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _save_positions(
    layout: ProjectLayout, positions: dict[str, dict[str, list[float]]]
) -> None:
    path = _positions_path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write so partial writes can't corrupt the file.
    fd, tmp = tempfile.mkstemp(prefix="positions-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(positions, fh)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _parse_ports(raw: Any) -> list[dict[str, Any]]:
    """Validate the ``ports`` array shared by POST /node and template bodies:
    ``[{name, direction in|out, port_type?}]`` → cleaned copies, 422 on shape
    errors."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="ports must be a list")
    cleaned: list[dict[str, Any]] = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            raise HTTPException(status_code=422, detail=f"ports[{i}] must be an object")
        pname = p.get("name")
        direction = p.get("direction")
        port_type = p.get("port_type", "any")
        if not isinstance(pname, str) or not pname.strip():
            raise HTTPException(status_code=422, detail=f"ports[{i}].name is required")
        if direction not in ("in", "out"):
            raise HTTPException(
                status_code=422, detail=f"ports[{i}].direction must be 'in' or 'out'"
            )
        if not isinstance(port_type, str) or not port_type.strip():
            port_type = "any"
        cleaned.append(
            {"name": pname.strip(), "direction": direction, "port_type": port_type.strip()}
        )
    return cleaned


def _templates_path(layout: ProjectLayout) -> Path:
    return layout.dot_dir / "ui" / "templates.json"


def _load_templates(layout: ProjectLayout) -> dict[str, dict[str, Any]]:
    path = _templates_path(layout)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        # Corrupt UI state shouldn't take down the API; pretend it's empty so
        # the next save overwrites cleanly.
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _save_templates(layout: ProjectLayout, templates: dict[str, dict[str, Any]]) -> None:
    path = _templates_path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="templates-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(templates, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
