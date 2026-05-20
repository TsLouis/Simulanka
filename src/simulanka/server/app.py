from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from simulanka.layout.project import ProjectLayout
from simulanka.storage.entity_store import iter_edges, iter_nodes, iter_ports

DEV_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def create_app(layout: ProjectLayout | None = None) -> FastAPI:
    if layout is None:
        layout = ProjectLayout.require()

    app = FastAPI(title="Simulanka Graph API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEV_ORIGINS),
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/graph")
    def get_graph(
        root: str | None = Query(default=None),
        depth: int = Query(default=1, ge=0, le=5),
    ) -> dict[str, Any]:
        return _build_payload(layout, root, depth)

    return app


def _build_payload(
    layout: ProjectLayout, root: str | None, depth: int
) -> dict[str, Any]:
    """Return {root, nodes, edges, ports} per docs/design.md §12.2.

    Containment is read from Node.parent_id (denormalised cache of `contains`
    edges maintained by the kernel). depth=N expands N hops of children below
    the root (or below the implicit top-level when root is None).
    Edges are included only when both endpoints fall in the included set.
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

    ports_of: dict[str, list[str]] = {}
    ports_payload: list[dict[str, Any]] = []
    for p in iter_ports(layout):
        if p.node_id in included:
            ports_of.setdefault(p.node_id, []).append(p.id)
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

    edges_payload: list[dict[str, Any]] = []
    for e in iter_edges(layout):
        if e.source_id in included and e.target_id in included:
            edges_payload.append(
                {
                    "id": e.id,
                    "type": e.type,
                    "src": e.source_id,
                    "dst": e.target_id,
                    "src_port": e.source_port_id,
                    "dst_port": e.target_port_id,
                    "attrs": e.attrs,
                }
            )

    nodes_payload = [
        {
            "id": n.id,
            "type": n.type,
            "name": n.name,
            "parent_id": n.parent_id,
            "attrs": n.attrs,
            "ports": ports_of.get(n.id, []),
        }
        for nid, n in nodes_by_id.items()
        if nid in included
    ]

    return {
        "root": root,
        "nodes": nodes_payload,
        "edges": edges_payload,
        "ports": ports_payload,
    }
