from __future__ import annotations

from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Node, Port
from simulanka.storage.entity_store import (
    find_port,
    iter_nodes,
    iter_ports,
    load_node,
    load_port,
    node_exists,
    port_exists,
)


class ResolveError(ValueError):
    """Selector could not be resolved."""


def resolve_node(layout: ProjectLayout, selector: str) -> Node:
    """Resolve a selector to a Node. Supports stable id, absolute `/a/b` path,
    or a bare name when it uniquely identifies one node — same convention as
    ``resolve_port``."""
    if not selector:
        raise ResolveError("Empty selector.")

    if selector.startswith("nod_"):
        if not node_exists(layout, selector):
            raise ResolveError(f"No node with id `{selector}`.")
        return load_node(layout, selector)

    if selector.startswith("/"):
        return _resolve_path(layout, selector)

    return _resolve_unique_name(layout, selector)


def resolve_port(layout: ProjectLayout, selector: str) -> Port:
    """Resolve a selector to a Port. Supports id, `/path.name`, `nodename.name`."""
    if not selector:
        raise ResolveError("Empty selector.")

    if selector.startswith("prt_"):
        if not port_exists(layout, selector):
            raise ResolveError(f"No port with id `{selector}`.")
        return load_port(layout, selector)

    if "." not in selector:
        raise ResolveError(
            f"Port selector `{selector}` must be `prt_...`, `/path.name`, or `nodename.name`."
        )

    node_part, _, port_name = selector.rpartition(".")
    if not node_part or not port_name:
        raise ResolveError(f"Malformed port selector `{selector}`.")

    if node_part.startswith("/") or node_part.startswith("nod_"):
        node = resolve_node(layout, node_part)
    else:
        node = _resolve_unique_name(layout, node_part)

    port = find_port(layout, node.id, port_name)
    if port is None:
        existing = ", ".join(p.name for p in iter_ports(layout) if p.node_id == node.id) or "(none)"
        raise ResolveError(
            f"Node `{node.name}` ({node.id}) has no port `{port_name}`. "
            f"Existing ports: {existing}."
        )
    return port


def _resolve_path(layout: ProjectLayout, path: str) -> Node:
    parts = [p for p in path.split("/") if p]
    if not parts:
        raise ResolveError("Root path `/` does not address a node.")

    nodes_by_id = {n.id: n for n in iter_nodes(layout)}
    children_by_parent: dict[str | None, list[Node]] = {}
    for n in nodes_by_id.values():
        children_by_parent.setdefault(n.parent_id, []).append(n)

    current_parent: str | None = None
    current: Node | None = None
    walked: list[str] = []
    for part in parts:
        siblings = children_by_parent.get(current_parent, [])
        matches = [s for s in siblings if s.name == part]
        walked.append(part)
        if not matches:
            ctx = "/" + "/".join(walked[:-1]) if walked[:-1] else "(root)"
            raise ResolveError(f"No node `{part}` under {ctx}.")
        if len(matches) > 1:
            ctx = "/" + "/".join(walked)
            candidates = ", ".join(m.id for m in matches)
            raise ResolveError(f"Ambiguous `{ctx}`: matches {candidates}.")
        current = matches[0]
        current_parent = current.id

    assert current is not None
    return current


def _resolve_unique_name(layout: ProjectLayout, name: str) -> Node:
    matches = [n for n in iter_nodes(layout) if n.name == name]
    if not matches:
        raise ResolveError(f"No node named `{name}`.")
    if len(matches) > 1:
        candidates = ", ".join(n.id for n in matches)
        raise ResolveError(f"Name `{name}` is ambiguous: {candidates}. Use a path or id.")
    return matches[0]
