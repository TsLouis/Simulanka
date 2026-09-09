"""S6 可信度: query-time trust levels + provenance backtrack (frontend.md S6).

Two hard principles (2026-07-10): trust is computed at query time from
existing stamps and never persisted; lineage is *shown* hop by hop, never
folded into one score — the graph exists so the human can see *why*
something is trusted. Nodes and edges are levelled separately (a supports
edge is the analyst's judgment, the evidence node is machine measurement —
often different levels; that is exactly why the chain is not folded).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any, Literal

from simulanka.layout.project import ProjectLayout
from simulanka.registry.builtin import DEFAULT_REGISTRY
from simulanka.registry.profiles import Registry
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import iter_edges, iter_nodes

TrustLevel = Literal["human", "constructed", "reviewed", "checked", "unreviewed"]

_SUPPORT_EDGES = ("supports", "contradicts")


def trust_level(attrs: Mapping[str, Any]) -> TrustLevel:
    """Deterministic mapping over existing stamps, by priority.

    `human` reads the only human-verdict stamp we mint (`verdict_by="user"`,
    set by accept/verdict endpoints); `constructed` is machine observation
    (importer trace, evidence extract, system lineage edges); `reviewed` is
    the analyst's distill pass (plan ingest); `checked` is reserved for the
    quick-check stamp vocabulary (dynamic-phase tools). Anything unstamped is
    honestly `unreviewed` — 「未定」应显眼地不显眼.
    """
    if attrs.get("verdict_by") == "user":
        return "human"
    if attrs.get("source") in ("trace", "machine"):
        return "constructed"
    if attrs.get("reviewed_in"):
        return "reviewed"
    if attrs.get("checked_by"):
        return "checked"
    return "unreviewed"


def node_trust(
    node: Node,
    *,
    registry: Registry = DEFAULT_REGISTRY,
) -> TrustLevel | None:
    """Trust badge for a node whose resolved Profile opts into trust semantics."""
    profile = registry.node(node.type)
    if profile is None or "trust_subject" not in profile.capabilities:
        return None
    return trust_level(node.attrs)


def provenance_chain(
    layout: ProjectLayout,
    node_id: str,
    *,
    registry: Registry = DEFAULT_REGISTRY,
) -> list[dict[str, Any]]:
    """Fixed-edge-set backtrack: claim/hypothesis ← supports/contradicts ←
    evidence ← produces (or parent) ← run —fulfills→ task —parent→ experiment
    —plan_file→ plan file node.

    Returns the chain in BFS discovery order, start node first (via_edge is
    None there). Structural hops (parent containment, the plan_file attr)
    have no edge entity to level, so their via_edge_trust is None. visited
    guards cycles; expansion is sorted by (id, via) for determinism.
    Raises KeyError on an unknown start node.
    """
    nodes_by_id: dict[str, Node] = {n.id: n for n in iter_nodes(layout)}
    if node_id not in nodes_by_id:
        raise KeyError(node_id)
    edges = list(iter_edges(layout))

    def hop(n: Node, via: str | None, via_trust: TrustLevel | None) -> dict[str, Any]:
        return {
            "id": n.id,
            "type": n.type,
            "name": n.name,
            "trust": node_trust(n, registry=registry),
            "via_edge": via,
            "via_edge_trust": via_trust,
        }

    def upstream(n: Node) -> list[tuple[Node, str, TrustLevel | None]]:
        out: list[tuple[Node, str, TrustLevel | None]] = []
        if n.type in ("claim", "hypothesis"):
            for e in edges:
                if e.type in _SUPPORT_EDGES and e.target_id == n.id:
                    src = nodes_by_id.get(e.source_id)
                    if src is not None:
                        out.append((src, e.type, trust_level(e.attrs)))
        elif n.type == "evidence":
            for e in edges:
                if e.type == "produces" and e.target_id == n.id:
                    src = nodes_by_id.get(e.source_id)
                    if src is not None:
                        out.append((src, "produces", trust_level(e.attrs)))
            if not out and n.parent_id is not None:
                parent = nodes_by_id.get(n.parent_id)
                if parent is not None and parent.type == "run":
                    out.append((parent, "parent", None))
        elif n.type == "run":
            for e in edges:
                if e.type == "fulfills" and e.source_id == n.id:
                    dst = nodes_by_id.get(e.target_id)
                    if dst is not None:
                        out.append((dst, "fulfills", trust_level(e.attrs)))
        elif n.type == "task":
            parent = nodes_by_id.get(n.parent_id) if n.parent_id else None
            if parent is not None and parent.type == "experiment":
                out.append((parent, "parent", None))
        elif n.type == "experiment":
            plan_file = n.attrs.get("plan_file")
            if isinstance(plan_file, str):
                for cand in nodes_by_id.values():
                    if cand.type == "file" and cand.attrs.get("fs_path") == plan_file:
                        out.append((cand, "plan_file", None))
        return sorted(out, key=lambda t: (t[0].id, t[1]))

    start = nodes_by_id[node_id]
    chain = [hop(start, None, None)]
    visited = {start.id}
    frontier: deque[Node] = deque([start])
    while frontier:
        current = frontier.popleft()
        for nxt, via, via_trust in upstream(current):
            if nxt.id in visited:
                continue
            visited.add(nxt.id)
            chain.append(hop(nxt, via, via_trust))
            frontier.append(nxt)
    return chain
