from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from simulanka.kernel.events import Event, append_event
from simulanka.kernel.ids import new_id
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    CreatePortOp,
    IntentOp,
    PatchIntent,
    Receipt,
    UpdateAttrsOp,
)
from simulanka.kernel.manifest import compute_content_hash, load_manifest, write_manifest
from simulanka.kernel.migration import check_versions
from simulanka.kernel.resolver import resolve_node, resolve_port
from simulanka.kernel.validator import (
    ValidationError,
    validate_edge,
    validate_node,
    validate_port,
)
from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Edge, Node, Port
from simulanka.storage.entity_store import (
    list_ports_of,
    save_edge,
    save_node,
    save_port,
)


class VersionConflict(RuntimeError):
    """base_graph_version did not match current manifest.graph_version."""


@dataclass
class _Pending:
    nodes: list[Node]
    edges: list[Edge]
    ports: list[Port]
    updated_nodes: list[Node]
    canonical_ops: list[dict[str, Any]]


def apply_patch_now(
    layout: ProjectLayout,
    *,
    ops: list[IntentOp],
    actor: str,
    note: str | None = None,
) -> Receipt:
    """Convenience wrapper: build a ``PatchIntent`` from the live ``graph_version``.

    Use when the caller has no reason to construct the intent itself and just
    wants to land *ops* atomically against the current head. The single source
    of the ``graph_version`` read prevents the off-by-one window that occurs
    when callers load the manifest, build ops, then call apply_patch.
    """
    return apply_patch(
        layout,
        PatchIntent(
            ops=ops,
            actor=actor,
            base_graph_version=load_manifest(layout).graph_version,
            note=note,
        ),
    )


def apply_patch(layout: ProjectLayout, intent: PatchIntent) -> Receipt:
    check_versions(layout)
    manifest = load_manifest(layout)
    if intent.base_graph_version != manifest.graph_version:
        raise VersionConflict(
            f"base_graph_version={intent.base_graph_version} but "
            f"current graph_version={manifest.graph_version}. Re-read and retry."
        )
    if not intent.ops:
        raise ValueError("PatchIntent.ops is empty.")

    now = datetime.now(timezone.utc)
    pending = _Pending(
        nodes=[], edges=[], ports=[], updated_nodes=[], canonical_ops=[],
    )
    errors: list[str] = []

    for idx, op in enumerate(intent.ops):
        errors.extend(_apply_op(layout, op, intent.actor, now, pending, op_index=idx))

    if errors:
        raise ValidationError("; ".join(errors))

    for node in pending.nodes:
        save_node(layout, node)
    for port in pending.ports:
        save_port(layout, port)
    for edge in pending.edges:
        save_edge(layout, edge)
    for node in pending.updated_nodes:
        save_node(layout, node)

    new_version = manifest.graph_version + 1
    event = Event(
        id=new_id("evt"),
        at=now,
        actor=intent.actor,
        kind="commit",
        base_graph_version=intent.base_graph_version,
        graph_version=new_version,
        note=intent.note,
        ops=pending.canonical_ops,
    )
    append_event(layout, event)

    manifest = manifest.model_copy(
        update={
            "graph_version": new_version,
            "content_hash": compute_content_hash(layout),
        }
    )
    write_manifest(layout, manifest)

    return Receipt(
        graph_version=new_version,
        event_id=event.id,
        nodes=[n.id for n in pending.nodes],
        edges=[e.id for e in pending.edges],
        ports=[p.id for p in pending.ports],
        updated_nodes=[n.id for n in pending.updated_nodes],
    )


def _apply_op(
    layout: ProjectLayout,
    op: IntentOp,
    actor: str,
    now: datetime,
    pending: _Pending,
    *,
    op_index: int,
) -> list[str]:
    prefix = f"op[{op_index}] {op.kind}"
    if isinstance(op, CreateNodeOp):
        return _handle_create_node(layout, op, actor, now, pending, prefix=prefix)
    if isinstance(op, CreatePortOp):
        return _handle_create_port(layout, op, actor, now, pending, prefix=prefix)
    if isinstance(op, CreateEdgeOp):
        return _handle_create_edge(layout, op, actor, now, pending, prefix=prefix)
    if isinstance(op, UpdateAttrsOp):
        return _handle_update_attrs(layout, op, pending, prefix=prefix)
    raise NotImplementedError(f"Unsupported op: {op!r}")  # pragma: no cover


def _handle_create_node(
    layout: ProjectLayout,
    op: CreateNodeOp,
    actor: str,
    now: datetime,
    pending: _Pending,
    *,
    prefix: str,
) -> list[str]:
    if not op.name:
        return [f"{prefix}: name must be non-empty."]
    if not op.type:
        return [f"{prefix}: type must be non-empty."]

    parent_node: Node | None = None
    if op.parent is not None:
        try:
            parent_node = resolve_node(layout, op.parent)
        except ValueError as exc:
            return [f"{prefix}: {exc}"]

    node = Node(
        id=new_id("nod"),
        type=op.type,
        name=op.name,
        parent_id=parent_node.id if parent_node else None,
        attrs=op.attrs,
        created_at=now,
        created_by=actor,
    )
    errors = [f"{prefix}: {e}" for e in validate_node(
        node, parent_type=parent_node.type if parent_node else None
    )]
    if errors:
        return errors

    pending.nodes.append(node)
    pending.canonical_ops.append(
        {
            "kind": "create_node",
            "entity_id": node.id,
            "type": node.type,
            "name": node.name,
            "parent_id": node.parent_id,
        }
    )

    # Dual-write: a `contains` edge keeps the layered hierarchy authoritative.
    if parent_node is not None:
        edge = Edge(
            id=new_id("edg"),
            type="contains",
            source_id=parent_node.id,
            target_id=node.id,
            created_at=now,
            created_by=actor,
        )
        edge_errors = [f"{prefix}: contains: {e}" for e in validate_edge(
            edge,
            source_node=parent_node,
            target_node=node,
            source_port=None,
            target_port=None,
        )]
        if edge_errors:
            return edge_errors
        pending.edges.append(edge)
        pending.canonical_ops.append(
            {
                "kind": "create_edge",
                "entity_id": edge.id,
                "type": "contains",
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "implicit": True,
            }
        )

    return []


def _handle_create_port(
    layout: ProjectLayout,
    op: CreatePortOp,
    actor: str,
    now: datetime,
    pending: _Pending,
    *,
    prefix: str,
) -> list[str]:
    try:
        node = resolve_node(layout, op.node)
    except ValueError as exc:
        return [f"{prefix}: {exc}"]

    existing = list_ports_of(layout, node.id) + [p for p in pending.ports if p.node_id == node.id]
    port = Port(
        id=new_id("prt"),
        node_id=node.id,
        name=op.name,
        direction=op.direction,
        port_type=op.port_type,
        attrs=op.attrs,
        created_at=now,
        created_by=actor,
    )
    errors = [f"{prefix}: {e}" for e in validate_port(port, node_ports=existing)]
    if errors:
        return errors

    pending.ports.append(port)
    pending.canonical_ops.append(
        {
            "kind": "create_port",
            "entity_id": port.id,
            "node_id": port.node_id,
            "name": port.name,
            "direction": port.direction,
            "port_type": port.port_type,
        }
    )
    return []


def _handle_create_edge(
    layout: ProjectLayout,
    op: CreateEdgeOp,
    actor: str,
    now: datetime,
    pending: _Pending,
    *,
    prefix: str,
) -> list[str]:
    source_node, source_port = _resolve_endpoint(layout, op.source)
    target_node, target_port = _resolve_endpoint(layout, op.target)

    edge = Edge(
        id=new_id("edg"),
        type=op.type,
        source_id=source_node.id,
        target_id=target_node.id,
        source_port_id=source_port.id if source_port else None,
        target_port_id=target_port.id if target_port else None,
        attrs=op.attrs,
        created_at=now,
        created_by=actor,
    )
    errors = [f"{prefix}: {e}" for e in validate_edge(
        edge,
        source_node=source_node,
        target_node=target_node,
        source_port=source_port,
        target_port=target_port,
    )]
    if errors:
        return errors

    pending.edges.append(edge)
    pending.canonical_ops.append(
        {
            "kind": "create_edge",
            "entity_id": edge.id,
            "type": edge.type,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "source_port_id": edge.source_port_id,
            "target_port_id": edge.target_port_id,
        }
    )
    return []


def _handle_update_attrs(
    layout: ProjectLayout,
    op: UpdateAttrsOp,
    pending: _Pending,
    *,
    prefix: str,
) -> list[str]:
    try:
        existing = resolve_node(layout, op.target)
    except ValueError as exc:
        return [f"{prefix}: {exc}"]

    # Earlier ops in the same patch may have already updated this node; honor
    # the latest pending version if present.
    for staged in pending.updated_nodes:
        if staged.id == existing.id:
            existing = staged
            break

    merged = {**existing.attrs, **op.attrs}
    updated = existing.model_copy(update={"attrs": merged})

    # Replace any previously staged update for the same node.
    pending.updated_nodes = [n for n in pending.updated_nodes if n.id != existing.id]
    pending.updated_nodes.append(updated)

    pending.canonical_ops.append(
        {
            "kind": "update_attrs",
            "entity_id": existing.id,
            "changed_keys": sorted(op.attrs.keys()),
        }
    )
    return []


def _resolve_endpoint(layout: ProjectLayout, selector: str) -> tuple[Node, Port | None]:
    """Given a selector, return (node, optional port). Accepts node or port selectors."""
    if selector.startswith("prt_") or _looks_like_port_selector(selector):
        port = resolve_port(layout, selector)
        from simulanka.storage.entity_store import load_node

        return load_node(layout, port.node_id), port
    return resolve_node(layout, selector), None


def _looks_like_port_selector(selector: str) -> bool:
    # `/path.name` or `nodename.name` — port selectors contain a "." not at the start.
    if "." not in selector:
        return False
    return not selector.startswith(".")
