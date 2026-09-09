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
    DeleteEdgeOp,
    DeleteNodeOp,
    IntentOp,
    PatchIntent,
    Receipt,
    RenameNodeOp,
    UpdateAttrsOp,
)
from simulanka.kernel.manifest import compute_content_hash, load_manifest, write_manifest
from simulanka.kernel.migration import check_versions
from simulanka.kernel.resolver import resolve_node, resolve_port
from simulanka.kernel.validator import (
    ValidationError,
    build_validation_view,
    reserved_name_error,
    validate_edge,
    validate_node,
    validate_port,
)
from simulanka.layout.project import ProjectLayout
from simulanka.registry.builtin import DEFAULT_REGISTRY
from simulanka.registry.profiles import ProfileValidationView, Registry
from simulanka.schema.entities import Edge, Node, Port
from simulanka.storage.checkpoint import maybe_checkpoint
from simulanka.storage.entity_store import (
    delete_edge,
    delete_node,
    delete_port,
    iter_edges,
    iter_nodes,
    iter_ports,
    list_ports_of,
    load_edge,
    load_node,
    load_port,
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
    updated_edges: list[Edge]
    canonical_ops: list[dict[str, Any]]
    deleted_edges: list[Edge]
    deleted_nodes: list[Node]
    deleted_ports: list[Port]
    refs: dict[str, Node]  # intent-local @ref handles → pending nodes


def _validation_view(
    layout: ProjectLayout,
    pending: _Pending,
    *,
    extra_nodes: tuple[Node, ...] = (),
    extra_edges: tuple[Edge, ...] = (),
    extra_ports: tuple[Port, ...] = (),
) -> ProfileValidationView:
    nodes = {node.id: node for node in iter_nodes(layout)}
    edges = {edge.id: edge for edge in iter_edges(layout)}
    ports = {port.id: port for port in iter_ports(layout)}
    for node in (*pending.nodes, *pending.updated_nodes, *extra_nodes):
        nodes[node.id] = node
    for edge in (*pending.edges, *pending.updated_edges, *extra_edges):
        edges[edge.id] = edge
    for port in (*pending.ports, *extra_ports):
        ports[port.id] = port
    for node in pending.deleted_nodes:
        nodes.pop(node.id, None)
    for edge in pending.deleted_edges:
        edges.pop(edge.id, None)
    for port in pending.deleted_ports:
        ports.pop(port.id, None)
    return build_validation_view(
        nodes=nodes.values(),
        edges=edges.values(),
        ports=ports.values(),
    )


def apply_patch_now(
    layout: ProjectLayout,
    *,
    ops: list[IntentOp],
    actor: str,
    note: str | None = None,
    registry: Registry = DEFAULT_REGISTRY,
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
        registry=registry,
    )


def apply_patch(
    layout: ProjectLayout,
    intent: PatchIntent,
    *,
    registry: Registry = DEFAULT_REGISTRY,
) -> Receipt:
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
        nodes=[], edges=[], ports=[], updated_nodes=[], updated_edges=[],
        canonical_ops=[], deleted_edges=[], deleted_nodes=[], deleted_ports=[],
        refs={},
    )
    errors: list[str] = []

    for idx, op in enumerate(intent.ops):
        errors.extend(
            _apply_op(
                layout,
                op,
                intent.actor,
                now,
                pending,
                registry,
                op_index=idx,
            )
        )

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
    for edge in pending.updated_edges:
        save_edge(layout, edge)
    for edge in pending.deleted_edges:
        delete_edge(layout, edge.id)
    for port in pending.deleted_ports:
        delete_port(layout, port.id)
    for node in pending.deleted_nodes:
        delete_node(layout, node.id)

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

    # §13.6 撤回兜底: snapshot the whole dot-dir into the embedded git repo.
    # No-op until storage.checkpoint.ensure_repo has run (server startup).
    message = f"v{new_version} {intent.actor}"
    if intent.note:
        message = f"{message}: {intent.note}"
    maybe_checkpoint(layout, message)

    return Receipt(
        graph_version=new_version,
        event_id=event.id,
        nodes=[n.id for n in pending.nodes],
        edges=[e.id for e in pending.edges],
        ports=[p.id for p in pending.ports],
        updated_nodes=[n.id for n in pending.updated_nodes],
        updated_edges=[e.id for e in pending.updated_edges],
        deleted_edges=[e.id for e in pending.deleted_edges],
        deleted_nodes=[n.id for n in pending.deleted_nodes],
        deleted_ports=[p.id for p in pending.deleted_ports],
    )


def _apply_op(
    layout: ProjectLayout,
    op: IntentOp,
    actor: str,
    now: datetime,
    pending: _Pending,
    registry: Registry,
    *,
    op_index: int,
) -> list[str]:
    prefix = f"op[{op_index}] {op.kind}"
    if isinstance(op, CreateNodeOp):
        return _handle_create_node(
            layout, op, actor, now, pending, registry, prefix=prefix
        )
    if isinstance(op, CreatePortOp):
        return _handle_create_port(
            layout, op, actor, now, pending, registry, prefix=prefix
        )
    if isinstance(op, CreateEdgeOp):
        return _handle_create_edge(
            layout, op, actor, now, pending, registry, prefix=prefix
        )
    if isinstance(op, UpdateAttrsOp):
        return _handle_update_attrs(layout, op, pending, registry, prefix=prefix)
    if isinstance(op, RenameNodeOp):
        return _handle_rename_node(layout, op, pending, prefix=prefix)
    if isinstance(op, DeleteEdgeOp):
        return _handle_delete_edge(layout, op, pending, prefix=prefix)
    if isinstance(op, DeleteNodeOp):
        return _handle_delete_node(layout, op, pending, prefix=prefix)
    raise NotImplementedError(f"Unsupported op: {op!r}")  # pragma: no cover


def _handle_create_node(
    layout: ProjectLayout,
    op: CreateNodeOp,
    actor: str,
    now: datetime,
    pending: _Pending,
    registry: Registry,
    *,
    prefix: str,
) -> list[str]:
    if not op.name:
        return [f"{prefix}: name must be non-empty."]
    if not op.type:
        return [f"{prefix}: type must be non-empty."]

    parent_node: Node | None = None
    if op.parent is not None:
        if op.parent.startswith("@"):
            parent_node = pending.refs.get(op.parent[1:])
            if parent_node is None:
                return [
                    f"{prefix}: unknown ref `{op.parent}` "
                    "(no earlier create_node declared it)."
                ]
        else:
            try:
                parent_node = resolve_node(layout, op.parent)
            except ValueError as exc:
                return [f"{prefix}: {exc}"]

    if op.ref is not None:
        if not op.ref:
            return [f"{prefix}: ref must be non-empty when given."]
        if op.ref in pending.refs:
            return [f"{prefix}: ref `{op.ref}` already declared earlier in this patch."]

    node = Node(
        id=new_id("nod"),
        type=op.type,
        name=op.name,
        parent_id=parent_node.id if parent_node else None,
        attrs=op.attrs,
        created_at=now,
        created_by=actor,
    )
    errors = [
        f"{prefix}: {error}"
        for error in validate_node(
            node,
            parent_type=parent_node.type if parent_node else None,
            registry=registry,
            view=_validation_view(layout, pending, extra_nodes=(node,)),
        )
    ]
    if errors:
        return errors

    pending.nodes.append(node)
    if op.ref is not None:
        pending.refs[op.ref] = node
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
        edge_errors = [
            f"{prefix}: contains: {error}"
            for error in validate_edge(
                edge,
                source_node=parent_node,
                target_node=node,
                source_port=None,
                target_port=None,
                registry=registry,
                view=_validation_view(layout, pending, extra_edges=(edge,)),
            )
        ]
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
    registry: Registry,
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
    errors = [
        f"{prefix}: {error}"
        for error in validate_port(port, node_ports=existing, registry=registry)
    ]
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
    registry: Registry,
    *,
    prefix: str,
) -> list[str]:
    # Unresolvable endpoints are a validation error, not a crash: a caller (or
    # a stale client) can reference a node/port that no longer exists. Surface
    # it the way the other handlers do, so apply_patch raises ValidationError
    # rather than letting resolve_*'s ValueError escape uncaught.
    try:
        source_node, source_port = _resolve_endpoint(layout, op.source, pending)
    except ValueError as exc:
        return [f"{prefix}: source: {exc}"]
    try:
        target_node, target_port = _resolve_endpoint(layout, op.target, pending)
    except ValueError as exc:
        return [f"{prefix}: target: {exc}"]

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
    errors = [
        f"{prefix}: {error}"
        for error in validate_edge(
            edge,
            source_node=source_node,
            target_node=target_node,
            source_port=source_port,
            target_port=target_port,
            registry=registry,
            view=_validation_view(layout, pending, extra_edges=(edge,)),
        )
    ]
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
    registry: Registry,
    *,
    prefix: str,
) -> list[str]:
    if op.target.startswith("edg_"):
        return _handle_update_edge_attrs(
            layout, op, pending, registry, prefix=prefix
        )
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
    parent = load_node(layout, existing.parent_id) if existing.parent_id else None
    errors = [
        f"{prefix}: {error}"
        for error in validate_node(
            updated,
            parent_type=parent.type if parent is not None else None,
            registry=registry,
            view=_validation_view(layout, pending, extra_nodes=(updated,)),
            validation_kind="update",
        )
    ]
    if errors:
        return errors

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


def _handle_update_edge_attrs(
    layout: ProjectLayout,
    op: UpdateAttrsOp,
    pending: _Pending,
    registry: Registry,
    *,
    prefix: str,
) -> list[str]:
    from simulanka.storage.entity_store import edge_exists

    if not edge_exists(layout, op.target):
        return [f"{prefix}: edge `{op.target}` not found."]
    if any(e.id == op.target for e in pending.deleted_edges):
        return [f"{prefix}: edge `{op.target}` is deleted earlier in this patch."]

    existing = load_edge(layout, op.target)
    for staged in pending.updated_edges:
        if staged.id == existing.id:
            existing = staged
            break

    merged = {**existing.attrs, **op.attrs}
    updated = existing.model_copy(update={"attrs": merged})
    source_node = load_node(layout, existing.source_id)
    target_node = load_node(layout, existing.target_id)
    source_port = (
        load_port(layout, existing.source_port_id) if existing.source_port_id else None
    )
    target_port = (
        load_port(layout, existing.target_port_id) if existing.target_port_id else None
    )
    errors = [
        f"{prefix}: {error}"
        for error in validate_edge(
            updated,
            source_node=source_node,
            target_node=target_node,
            source_port=source_port,
            target_port=target_port,
            registry=registry,
            view=_validation_view(layout, pending, extra_edges=(updated,)),
            validation_kind="update",
        )
    ]
    if errors:
        return errors

    pending.updated_edges = [e for e in pending.updated_edges if e.id != existing.id]
    pending.updated_edges.append(updated)

    # source_id/target_id ride along so event consumers (SSE _affected) can
    # refresh the endpoint nodes without re-loading the edge.
    pending.canonical_ops.append(
        {
            "kind": "update_attrs",
            "entity_id": existing.id,
            "changed_keys": sorted(op.attrs.keys()),
            "source_id": existing.source_id,
            "target_id": existing.target_id,
        }
    )
    return []


def _handle_rename_node(
    layout: ProjectLayout,
    op: RenameNodeOp,
    pending: _Pending,
    *,
    prefix: str,
) -> list[str]:
    if not op.new_name:
        return [f"{prefix}: new_name must be non-empty."]
    reserved = reserved_name_error(op.new_name)
    if reserved:
        return [f"{prefix}: {reserved}"]
    try:
        existing = resolve_node(layout, op.target)
    except ValueError as exc:
        return [f"{prefix}: {exc}"]

    for staged in pending.updated_nodes:
        if staged.id == existing.id:
            existing = staged
            break

    old_name = existing.name

    # Sibling-unique under the same parent. Use on-disk view, then overlay any
    # pending creations/updates in the same patch so a rename in the same
    # PatchIntent as a CreateNodeOp still sees the new sibling.
    from simulanka.storage.entity_store import iter_nodes
    siblings: list[Node] = []
    for n in iter_nodes(layout):
        if n.parent_id == existing.parent_id and n.id != existing.id:
            siblings.append(n)
    for n in pending.nodes:
        if n.parent_id == existing.parent_id and n.id != existing.id:
            siblings.append(n)
    for n in pending.updated_nodes:
        # Overlay updated names onto the sibling view.
        siblings = [n if s.id == n.id else s for s in siblings]
    if any(s.name == op.new_name for s in siblings):
        scope = existing.parent_id or "(root)"
        return [f"{prefix}: sibling under `{scope}` already named `{op.new_name}`."]

    updated = existing.model_copy(update={"name": op.new_name})
    pending.updated_nodes = [n for n in pending.updated_nodes if n.id != existing.id]
    pending.updated_nodes.append(updated)

    pending.canonical_ops.append(
        {
            "kind": "rename_node",
            "entity_id": existing.id,
            "old_name": old_name,
            "new_name": op.new_name,
        }
    )
    return []


def _handle_delete_edge(
    layout: ProjectLayout,
    op: DeleteEdgeOp,
    pending: _Pending,
    *,
    prefix: str,
) -> list[str]:
    from simulanka.storage.entity_store import edge_exists

    if not edge_exists(layout, op.edge):
        return [f"{prefix}: edge `{op.edge}` not found."]
    if any(e.id == op.edge for e in pending.deleted_edges):
        return []  # idempotent within a single patch
    edge = load_edge(layout, op.edge)
    if edge.type == "contains":
        return [
            f"{prefix}: refusing to delete structural `contains` edge "
            f"`{op.edge}` — it backs the node hierarchy."
        ]

    pending.deleted_edges.append(edge)
    pending.canonical_ops.append(
        {
            "kind": "delete_edge",
            "entity_id": edge.id,
            "type": edge.type,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
        }
    )
    return []


def _handle_delete_node(
    layout: ProjectLayout,
    op: DeleteNodeOp,
    pending: _Pending,
    *,
    prefix: str,
) -> list[str]:
    from simulanka.storage.entity_store import iter_edges, iter_nodes

    try:
        node = resolve_node(layout, op.node)
    except ValueError as exc:
        return [f"{prefix}: {exc}"]
    if any(n.id == node.id for n in pending.deleted_nodes):
        return []  # idempotent within a single patch

    child_count = sum(1 for n in iter_nodes(layout) if n.parent_id == node.id)
    if child_count > 0:
        return [
            f"{prefix}: node `{node.name}` has {child_count} children — "
            "empty it first (subtree deletion must be explicit, bottom-up)."
        ]

    # Cascade what is *of* the node: its ports and every incident edge —
    # including the parent's `contains` edge, whose removal here reverses the
    # create-time dual-write (Edge.source_id/target_id are node ids, so the
    # incident sweep also catches port-attached data_flow edges).
    already = {e.id for e in pending.deleted_edges}
    doomed_edges = [
        e
        for e in iter_edges(layout)
        if (e.source_id == node.id or e.target_id == node.id) and e.id not in already
    ]
    ports = list_ports_of(layout, node.id)

    pending.deleted_edges.extend(doomed_edges)
    pending.deleted_ports.extend(ports)
    pending.deleted_nodes.append(node)
    pending.canonical_ops.append(
        {
            "kind": "delete_node",
            "entity_id": node.id,
            "type": node.type,
            "name": node.name,
            "parent_id": node.parent_id,
            "deleted_ports": sorted(p.id for p in ports),
            "deleted_edges": sorted(e.id for e in doomed_edges),
        }
    )
    return []


def _resolve_endpoint(
    layout: ProjectLayout, selector: str, pending: _Pending
) -> tuple[Node, Port | None]:
    """Given a selector, return (node, optional port). Accepts node or port selectors,
    plus intent-local ``@ref`` handles (node-level only — pending nodes have no ports)."""
    if selector.startswith("@"):
        node = pending.refs.get(selector[1:])
        if node is None:
            raise ValueError(f"unknown ref `{selector}` (no earlier create_node declared it).")
        return node, None
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
