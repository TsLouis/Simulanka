"""The §13.6 disagreement set, computed from edge attrs.

Single source shared by the server (``/disagreements``, discussion opening
context) and ``brief export`` (the one-line count) — the set is never
computed twice in two places.
"""

from __future__ import annotations

from typing import Any

from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Edge
from simulanka.storage.entity_store import iter_edges, load_node


def edge_payload(e: Edge) -> dict[str, Any]:
    """Wire shape for an edge (server JSON + discussion context)."""
    return {
        "id": e.id,
        "type": e.type,
        "src": e.source_id,
        "dst": e.target_id,
        "src_port": e.source_port_id,
        "dst_port": e.target_port_id,
        "attrs": e.attrs,
    }


def disagreement_list(layout: ProjectLayout) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    # Endpoint names ride along: the disagreement set spans the whole graph,
    # so the frontend's current-view name map can't resolve edges from other
    # views (they'd render as raw node ids), and the discussion opening
    # context reads better with names than ULIDs.
    names: dict[str, str] = {}

    def node_name(node_id: str) -> str:
        if node_id not in names:
            try:
                names[node_id] = load_node(layout, node_id).name
            except FileNotFoundError:
                names[node_id] = node_id
        return names[node_id]

    for e in iter_edges(layout):
        if e.type != "data_flow":
            continue
        a = e.attrs
        reasons: list[str] = []
        if (
            a.get("source") == "agent"
            and a.get("status") == "proposed"
            and a.get("verdict") == "wrong"
            and a.get("verdict_by") == "user"
        ):
            reasons.append("user_rejected_ghost")
        if (
            a.get("source") == "user"
            and a.get("verdict") in ("wrong", "uncertain")
            and a.get("verdict_by") == "agent"
        ):
            reasons.append("agent_flagged_user_edge")
        if a.get("verdict") == "disputed":
            reasons.append("disputed")
        if a.get("discuss") is True:
            reasons.append("manual")
        if reasons:
            out.append({
                **edge_payload(e),
                "reasons": reasons,
                "src_name": node_name(e.source_id),
                "dst_name": node_name(e.target_id),
            })
    return out
