from __future__ import annotations

from simulanka.registry.builtin import DEFAULT_REGISTRY
from simulanka.registry.profiles import Registry
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
    registry: Registry = DEFAULT_REGISTRY,
) -> list[str]:
    errors: list[str] = []
    reserved = reserved_name_error(node.name)
    if reserved:
        errors.append(reserved)
    spec = registry.node(node.type)
    if spec is None:
        errors.append(f"Unknown node type `{node.type}`.")
        return errors
    canonical_parent = parent_type
    if parent_type is not None:
        parent_profile = registry.node(parent_type)
        if parent_profile is None:
            errors.append(f"Unknown parent node type `{parent_type}`.")
            return errors
        canonical_parent = parent_profile.key
    if not spec.accepts_parent(canonical_parent):
        allowed = ", ".join(sorted(repr(p) for p in spec.allow_parents))
        errors.append(
            f"Node type `{node.type}` cannot have parent of type "
            f"`{parent_type}` (allowed: {allowed})."
        )
    if spec.closed_attrs:
        unknown_attrs = node.attrs.keys() - spec.attrs_fields.keys()
        if unknown_attrs:
            errors.append(
                f"Node type `{node.type}` has unknown attrs: {sorted(unknown_attrs)}."
            )
    return errors


def validate_port(
    port: Port,
    *,
    node_ports: list[Port],
    registry: Registry = DEFAULT_REGISTRY,
) -> list[str]:
    errors: list[str] = []
    if registry.resolve_port_key(port.port_type) is None:
        errors.append(
            f"Unknown port_type `{port.port_type}` "
            f"(registered: {sorted(registry.port_types)})."
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
    registry: Registry = DEFAULT_REGISTRY,
) -> list[str]:
    errors: list[str] = []
    spec = registry.edge(edge.type)
    if spec is None:
        errors.append(f"Unknown edge type `{edge.type}`.")
        return errors

    source_profile = registry.node(source_node.type)
    target_profile = registry.node(target_node.type)
    if source_profile is None:
        errors.append(f"Unknown source node type `{source_node.type}`.")
    elif not spec.accepts_source(source_profile):
        errors.append(
            f"Edge `{edge.type}` rejects source node type `{source_node.type}` "
            f"(allowed: {sorted(spec.source_profiles)})."
        )
    if target_profile is None:
        errors.append(f"Unknown target node type `{target_node.type}`.")
    elif not spec.accepts_target(target_profile):
        errors.append(
            f"Edge `{edge.type}` rejects target node type `{target_node.type}` "
            f"(allowed: {sorted(spec.target_profiles)})."
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
        # Tunnel exemption (§12.4 subgraph IO, 2026-07-14): a container's own
        # port has two faces. From inside the container its in-port is a
        # source (parent.in → child.in) and its out-port is a sink
        # (child.out → parent.out) — exactly one containment level, the
        # ComfyUI/UE5 subgraph-boundary semantics.
        tunnel_in = (
            source_port.direction == "in" and target_node.parent_id == source_node.id
        )
        tunnel_out = (
            target_port.direction == "out" and source_node.parent_id == target_node.id
        )
        if (
            spec.source_port_direction
            and source_port.direction != spec.source_port_direction
            and not tunnel_in
        ):
            errors.append(
                f"Source port `{source_port.name}` direction is "
                f"`{source_port.direction}`, expected `{spec.source_port_direction}`."
            )
        if (
            spec.target_port_direction
            and target_port.direction != spec.target_port_direction
            and not tunnel_out
        ):
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
