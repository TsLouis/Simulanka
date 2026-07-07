from __future__ import annotations

from simulanka.registry.builtin import EDGE_TYPES, NODE_TYPES, PORT_TYPES
from simulanka.schema.entities import Edge, Node, Port


class ValidationError(ValueError):
    """One or more invariants violated."""


_RESERVED_NAME_PREFIXES = ("nod_", "edg_", "prt_")


def reserved_name_error(name: str) -> str | None:
    """Names that would be hijacked by selector syntax are reserved.

    `edg_*` bare names get routed to the edge branch of UpdateAttrsOp
    (2026-06-12 review), `nod_`/`prt_` shadow id selectors the same way, and a
    leading `@` collides with intent-local ref handles. Enforced on create and
    rename — the two places a name enters the graph.
    """
    if name.startswith(_RESERVED_NAME_PREFIXES):
        return f"Name `{name}` uses a reserved id prefix (nod_/edg_/prt_)."
    if name.startswith("@"):
        return f"Name `{name}` may not start with `@` (reserved for intent-local refs)."
    return None


def validate_node(
    node: Node,
    *,
    parent_type: str | None,
) -> list[str]:
    errors: list[str] = []
    reserved = reserved_name_error(node.name)
    if reserved:
        errors.append(reserved)
    spec = NODE_TYPES.get(node.type)
    if spec is None:
        errors.append(f"Unknown node type `{node.type}`.")
        return errors
    if not spec.accepts_parent(parent_type):
        allowed = ", ".join(sorted(repr(p) for p in spec.allow_parents))
        errors.append(
            f"Node type `{node.type}` cannot have parent of type "
            f"`{parent_type}` (allowed: {allowed})."
        )
    return errors


def validate_port(port: Port, *, node_ports: list[Port]) -> list[str]:
    errors: list[str] = []
    if port.port_type not in PORT_TYPES:
        errors.append(
            f"Unknown port_type `{port.port_type}` (registered: {sorted(PORT_TYPES)})."
        )
    if any(other.name == port.name for other in node_ports):
        errors.append(
            f"Port `{port.name}` already exists on node `{port.node_id}`."
        )
    return errors


def validate_edge(
    edge: Edge,
    *,
    source_node: Node,
    target_node: Node,
    source_port: Port | None,
    target_port: Port | None,
) -> list[str]:
    errors: list[str] = []
    spec = EDGE_TYPES.get(edge.type)
    if spec is None:
        errors.append(f"Unknown edge type `{edge.type}`.")
        return errors

    if not spec.accepts_source_type(source_node.type):
        errors.append(
            f"Edge `{edge.type}` rejects source node type `{source_node.type}` "
            f"(allowed: {sorted(spec.source_node_types)})."
        )
    if not spec.accepts_target_type(target_node.type):
        errors.append(
            f"Edge `{edge.type}` rejects target node type `{target_node.type}` "
            f"(allowed: {sorted(spec.target_node_types)})."
        )

    if spec.needs_ports:
        if source_port is None or target_port is None:
            errors.append(
                f"Edge type `{edge.type}` requires explicit source and target ports."
            )
            return errors
        if source_port.node_id != source_node.id:
            errors.append(
                f"Source port `{source_port.id}` does not belong to source node "
                f"`{source_node.id}`."
            )
        if target_port.node_id != target_node.id:
            errors.append(
                f"Target port `{target_port.id}` does not belong to target node "
                f"`{target_node.id}`."
            )
        if spec.source_port_direction and source_port.direction != spec.source_port_direction:
            errors.append(
                f"Source port `{source_port.name}` direction is "
                f"`{source_port.direction}`, expected `{spec.source_port_direction}`."
            )
        if spec.target_port_direction and target_port.direction != spec.target_port_direction:
            errors.append(
                f"Target port `{target_port.name}` direction is "
                f"`{target_port.direction}`, expected `{spec.target_port_direction}`."
            )
    elif source_port is not None or target_port is not None:
        errors.append(
            f"Edge type `{edge.type}` does not use ports; "
            "source_port/target_port must be omitted."
        )

    return errors
