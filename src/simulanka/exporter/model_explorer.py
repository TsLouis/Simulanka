"""Export a Simulanka model subtree as Google Model Explorer JSON.

Model Explorer's adapter schema is hierarchy + edges:

* Each module → one ``GraphNode``. ``namespace`` is the slash-separated parent
  fqn (Model Explorer uses ``/`` to group nodes into collapsible regions);
  ``label`` is the leaf segment + class name in parens; ``id`` is the dotted
  fqn (unique within a model).
* Each Simulanka ``data_flow`` edge restricted to the subtree → an entry in
  the target's ``incomingEdges``.

The root ``model`` node itself is not emitted as a graph node — it *is* the
graph (its name becomes the graph's id/label). Modules at fqn depth 1 land
in the empty namespace (top-level of the canvas).

Reference: https://github.com/google-ai-edge/model-explorer/wiki/6.-Develop-Adapter-Extension
"""

from __future__ import annotations

from typing import Any

from simulanka.kernel.resolver import resolve_node
from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import iter_edges, iter_nodes


def to_model_explorer(layout: ProjectLayout, model_selector: str) -> dict[str, Any]:
    """Build a Model Explorer adapter dict for the model rooted at ``model_selector``.

    Returns a dict shaped as ``{"graphs": [{"id": ..., "label": ..., "nodes": [...]}]}``,
    serialisable to JSON for Model Explorer's file loader.
    """
    root = resolve_node(layout, model_selector)
    if root.type != "model":
        raise ValueError(
            f"selector {model_selector!r} resolves to a {root.type!r} node; "
            "expected a `model` node.",
        )

    nodes_by_id: dict[str, Node] = {}
    children_of: dict[str, list[str]] = {}
    for n in iter_nodes(layout):
        nodes_by_id[n.id] = n
        if n.parent_id is not None:
            children_of.setdefault(n.parent_id, []).append(n.id)

    # BFS the parent-id tree to find the subtree under the model.
    subtree: set[str] = set()
    queue = [root.id]
    while queue:
        nid = queue.pop()
        subtree.add(nid)
        queue.extend(children_of.get(nid, []))

    # fqn (dotted) for each subtree node. Importer-written module nodes already
    # carry `fqn` in attrs; for any other node-type that sneaks in, derive from
    # the parent chain.
    fqn_of: dict[str, str] = {root.id: ""}

    def _fqn(nid: str) -> str:
        if nid in fqn_of:
            return fqn_of[nid]
        n = nodes_by_id[nid]
        stored = n.attrs.get("fqn")
        if isinstance(stored, str):
            fqn_of[nid] = stored
            return stored
        parent_fqn = _fqn(n.parent_id) if n.parent_id else ""
        derived = f"{parent_fqn}.{n.name}" if parent_fqn else n.name
        fqn_of[nid] = derived
        return derived

    for nid in subtree:
        _fqn(nid)

    me_nodes: list[dict[str, Any]] = []
    me_id_for: dict[str, str] = {}  # simulanka node id → ME node id
    for nid in subtree:
        if nid == root.id:
            continue
        n = nodes_by_id[nid]
        fqn = fqn_of[nid]
        if "." in fqn:
            parent_fqn, _, leaf = fqn.rpartition(".")
        else:
            parent_fqn, leaf = "", fqn
        namespace = parent_fqn.replace(".", "/")
        cls = n.attrs.get("class_name", n.type)
        me_id_for[nid] = fqn
        # `incomingEdges` always present — the Model Explorer frontend expects
        # the key on every node even when the list is empty.
        me_nodes.append({
            "id": fqn,
            "label": f"{leaf} ({cls})",
            "namespace": namespace,
            "incomingEdges": [],
        })

    me_node_by_id = {n["id"]: n for n in me_nodes}
    for e in iter_edges(layout):
        if e.type != "data_flow":
            continue
        if e.source_id not in me_id_for or e.target_id not in me_id_for:
            continue
        me_node_by_id[me_id_for[e.target_id]]["incomingEdges"].append(
            {"sourceNodeId": me_id_for[e.source_id]},
        )

    # Wire form: `{"graphs": [Graph, ...]}` — the only object-shape the
    # Model Explorer frontend's built-in JSON loader recognises (it wraps
    # this into a GraphCollection internally, using the filename as label).
    return {
        "graphs": [
            {
                "id": root.name,
                "nodes": me_nodes,
            },
        ],
    }
