from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from simulanka.agent.harness import (
    CommandRunner,
    HarnessError,
    OpenCodeTurn,
    run_opencode_turn,
)
from simulanka.disagreements import disagreement_list, edge_payload
from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.events import Event, iter_events
from simulanka.kernel.intent import CreateEdgeOp, DeleteEdgeOp, Receipt, UpdateAttrsOp
from simulanka.kernel.manifest import load_manifest
from simulanka.kernel.validator import ValidationError
from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Edge
from simulanka.server.agent_ops import apply_agent_ops
from simulanka.storage.checkpoint import ensure_repo, repo_exists, tag_checkpoint
from simulanka.storage.entity_store import (
    iter_edges,
    iter_nodes,
    iter_ports,
    load_edge,
)

DEV_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

SSE_POLL_INTERVAL = 0.25  # seconds between event_log polls



def create_app(
    layout: ProjectLayout | None = None,
    *,
    opencode_runner: CommandRunner | None = None,
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

    app = FastAPI(title="Simulanka Graph API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEV_ORIGINS),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    @app.get("/graph")
    def get_graph(
        root: str | None = Query(default=None),
        depth: int = Query(default=1, ge=0, le=5),
    ) -> dict[str, Any]:
        return _build_payload(layout, root, depth)

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
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "deleted": receipt.deleted_edges,
            "graph_version": receipt.graph_version,
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
        )
        return {"edge_id": edge_id, "graph_version": receipt.graph_version}

    @app.get("/disagreements")
    def get_disagreements() -> dict[str, Any]:
        """The §13.6 disagreement set, computed from edge attrs (no extra
        state): ① ghosts the human rejected, ② human-drawn edges the agent's
        verify pass ruled wrong/uncertain, ③ disputed verdicts, ④ edges pulled
        in by hand. One edge can match several buckets — ``reasons`` lists all.
        """
        return {"disagreements": disagreement_list(layout)}

    # --- §13.6 discussion session: the agent op channel --------------------
    # One batch, one session (一批一场): /start snapshots the disagreement
    # set, tags a recovery point, and opens an opencode session; /message
    # continues it. Each turn's simulanka-ops blocks (parsed by the Codex
    # harness) pass through the agent_ops write-matrix gate — the agent
    # itself holds no write tools. Canvas updates ride the existing SSE.

    def _run_turn(
        message: str, *, session_id: str | None, model: str | None
    ) -> OpenCodeTurn:
        try:
            return run_opencode_turn(
                message,
                session_id=session_id,
                model=model,
                runner=opencode_runner,
            )
        except HarnessError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/discussion/start")
    def discussion_start(
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        """Open the batch discussion. Body: ``{model?}``."""
        model = body.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise HTTPException(status_code=422, detail="model must be a string")
        disagreements = disagreement_list(layout)
        if not disagreements:
            raise HTTPException(
                status_code=422, detail="no disagreements — nothing to discuss"
            )
        # §13.6 撤回兜底: the round start is the recovery target. Best-effort,
        # same as per-commit checkpoints — a broken git must not block talk.
        if repo_exists(layout):
            try:
                tag_checkpoint(layout, "discussion-start")
            except (OSError, subprocess.CalledProcessError) as exc:
                logging.getLogger(__name__).warning(
                    "discussion-start tag failed: %s", exc
                )
        turn = _run_turn(
            _opening_message(disagreements), session_id=None, model=model
        )
        if not turn.session_id:
            raise HTTPException(
                status_code=502, detail="opencode returned no session id"
            )
        state = {
            "session_id": turn.session_id,
            "model": model,
            "batch": [d["id"] for d in disagreements],
        }
        _save_discussion(layout, state)
        applied, rejected = apply_agent_ops(layout, turn.ops)
        return {
            **state,
            "reply": turn.text,
            "applied": applied,
            "rejected": rejected,
            "op_errors": turn.op_errors,
        }

    @app.post("/discussion/message")
    def discussion_message(
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        """One human turn in the active discussion. Body: ``{text}``."""
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=422, detail="text is required")
        state = _load_discussion(layout)
        if state is None:
            raise HTTPException(
                status_code=422,
                detail="no active discussion — POST /discussion/start first",
            )
        turn = _run_turn(
            text, session_id=state["session_id"], model=state.get("model")
        )
        applied, rejected = apply_agent_ops(layout, turn.ops)
        return {
            "session_id": state["session_id"],
            "reply": turn.text,
            "applied": applied,
            "rejected": rejected,
            "op_errors": turn.op_errors,
        }

    @app.get("/discussion")
    def discussion_state() -> dict[str, Any]:
        state = _load_discussion(layout)
        if state is None:
            return {"active": False}
        return {"active": True, **state}

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


def _apply_user_op(layout: ProjectLayout, op: UpdateAttrsOp, note: str) -> Receipt:
    """apply_patch_now with kernel rejections surfaced as 422 — e.g. the edge
    vanished between the endpoint's precondition check and the write."""
    try:
        return apply_patch_now(layout, ops=[op], actor="user", note=note)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _build_payload(
    layout: ProjectLayout, root: str | None, depth: int
) -> dict[str, Any]:
    """Return the subgraph payload per docs/design.md §12.2 / §12.4.

    Containment comes from Node.parent_id (denormalised cache of `contains`
    edges). depth=N expands N hops of children below root (or below the
    implicit top-level when root is None).

    - `edges`: both endpoints in the included set.
    - `boundary_edges`: exactly one endpoint in the included set. Only filled
      when root is given — at top-level there is no outside. The frontend
      projects these onto virtual boundary ports (§12.4).
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

    included: set[str] = set()
    if root is None:
        frontier = list(children_of.get(None, []))
    else:
        included.add(root)
        frontier = [root]
    included.update(frontier)

    for _ in range(depth):
        next_frontier: list[str] = []
        for nid in frontier:
            next_frontier.extend(children_of.get(nid, []))
        included.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break

    edges_payload: list[dict[str, Any]] = []
    boundary_payload: list[dict[str, Any]] = []
    external_ids: set[str] = set()
    external_port_ids: set[str] = set()
    for e in iter_edges(layout):
        src_in = e.source_id in included
        dst_in = e.target_id in included
        if src_in and dst_in:
            edges_payload.append(edge_payload(e))
        elif (src_in or dst_in) and root is not None:
            boundary_payload.append(edge_payload(e))
            external_ids.add(e.target_id if src_in else e.source_id)
            outside_port = e.target_port_id if src_in else e.source_port_id
            if outside_port is not None:
                external_port_ids.add(outside_port)

    # Included nodes' ports, plus the outside ports boundary edges point at —
    # without those the frontend can't label the far end of a cross-boundary
    # edge (§12.4 boundary ports, §13.6 panel endpoints).
    ports_of: dict[str, list[str]] = {}
    ports_payload: list[dict[str, Any]] = []
    for p in iter_ports(layout):
        if p.node_id in included:
            ports_of.setdefault(p.node_id, []).append(p.id)
        elif p.id not in external_port_ids:
            continue
        ports_payload.append(
            {
                "id": p.id,
                "node_id": p.node_id,
                "name": p.name,
                "side": p.direction,
                "port_type": p.port_type,
                "attrs": p.attrs,
            }
        )

    external_payload = [
        {
            "id": nid,
            "type": nodes_by_id[nid].type,
            "name": nodes_by_id[nid].name,
        }
        for nid in external_ids
        if nid in nodes_by_id
    ]

    nodes_payload = [
        {
            "id": n.id,
            "type": n.type,
            "name": n.name,
            "parent_id": n.parent_id,
            "attrs": n.attrs,
            "ports": ports_of.get(n.id, []),
            "child_count": len(children_of.get(n.id, [])),
        }
        for nid, n in nodes_by_id.items()
        if nid in included
    ]

    # Ancestor chain from top-level down to the root's direct parent. Lets the
    # frontend reconstruct the breadcrumb trail for a non-null root regardless
    # of how the user navigated there (drill-down, jump-external, deep link).
    ancestors: list[dict[str, Any]] = []
    if root is not None:
        cur = nodes_by_id[root].parent_id
        while cur is not None and cur in nodes_by_id:
            anc = nodes_by_id[cur]
            ancestors.append({"id": anc.id, "type": anc.type, "name": anc.name})
            cur = anc.parent_id
        ancestors.reverse()

    return {
        "root": root,
        "nodes": nodes_payload,
        "edges": edges_payload,
        "boundary_edges": boundary_payload,
        "external_nodes": external_payload,
        "ports": ports_payload,
        "ancestors": ancestors,
    }


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
    if not isinstance(data, dict) or not isinstance(data.get("session_id"), str):
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
