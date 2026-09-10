from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from simulanka.kernel.apply import apply_patch, apply_patch_now
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    CreatePortOp,
    DeleteEdgeOp,
    PatchIntent,
    UpdateAttrsOp,
)
from simulanka.kernel.manifest import load_manifest
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.registry import BUILTIN_PACKAGES, SOFTWARE_SERVICE_PACKAGE, Registry
from simulanka.server.app import create_app
from simulanka.storage.entity_store import (
    edge_exists,
    find_port,
    iter_edges,
    iter_nodes,
    load_edge,
    save_node,
)


def _seed_project(tmp_path: Path) -> ProjectLayout:
    """Init scaffolded project, then add a model with two child modules connected
    by a data_flow edge through ports."""
    layout = init_project(tmp_path).layout
    baselines = next(n for n in iter_nodes(layout) if n.name == "baselines")

    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="model", name="Net", parent=baselines.id, attrs={})],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")

    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(type="module", name="enc", parent=net_id, attrs={}),
                CreateNodeOp(type="module", name="dec", parent=net_id, attrs={}),
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")
    dec_id = next(n.id for n in iter_nodes(layout) if n.name == "dec")

    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreatePortOp(node=enc_id, name="out0", direction="out", port_type="tensor"),
                CreatePortOp(node=dec_id, name="in0", direction="in", port_type="tensor"),
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    enc_out = find_port(layout, enc_id, "out0")
    dec_in = find_port(layout, dec_id, "in0")
    assert enc_out is not None and dec_in is not None

    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateEdgeOp(
                    type="data_flow",
                    source=enc_out.id,
                    target=dec_in.id,
                    attrs={},
                ),
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    return layout


def test_get_graph_no_root_returns_top_level(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))

    resp = client.get("/graph")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["root"] is None
    assert payload["root_info"] is None
    # No root: top-level directories only — no Net (it lives under baselines).
    types = {n["type"] for n in payload["nodes"]}
    assert types == {"directory"}
    assert all(n["parent_id"] is None for n in payload["nodes"])
    # No root → no ancestor chain.
    assert payload["ancestors"] == []


def test_get_graph_root_returns_children_only(tmp_path: Path) -> None:
    """The view is the inside of one container: direct children only. The root
    itself never appears among nodes (it lives in root_info for the crumb),
    and its contains edges to the children are implicit in the view."""
    layout = _seed_project(tmp_path)
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")

    client = TestClient(create_app(layout))
    resp = client.get("/graph", params={"root": net_id})
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["root"] == net_id
    assert {
        key: payload["root_info"][key]
        for key in ("id", "type", "name")
    } == {"id": net_id, "type": "model", "name": "Net"}
    names = sorted(n["name"] for n in payload["nodes"])
    assert names == ["dec", "enc"]

    flows = [e for e in payload["edges"] if e["type"] == "data_flow"]
    assert len(flows) == 1
    enc_id = next(n["id"] for n in payload["nodes"] if n["name"] == "enc")
    dec_id = next(n["id"] for n in payload["nodes"] if n["name"] == "dec")
    assert flows[0]["src"] == enc_id
    assert flows[0]["dst"] == dec_id
    assert flows[0]["src_port"] is not None
    assert flows[0]["dst_port"] is not None

    sides = sorted(p["side"] for p in payload["ports"])
    assert sides == ["in", "out"]

    by_name = {n["name"]: n for n in payload["nodes"]}
    assert by_name["enc"]["child_count"] == 0
    assert by_name["dec"]["child_count"] == 0

    # Structural containment (baselines→Net, Net→enc/dec) never crosses into
    # boundary_edges — the nesting itself conveys it.
    assert payload["boundary_edges"] == []
    assert payload["external_nodes"] == []


def test_get_graph_ancestors_chain_from_root(tmp_path: Path) -> None:
    """root=enc returns the parent chain `baselines/Net` (top-down). The
    frontend uses this to rebuild crumbs after jump-external or deep-link
    loads with an arbitrary root."""
    layout = _seed_project(tmp_path)
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")
    baselines_id = next(n.id for n in iter_nodes(layout) if n.name == "baselines")

    client = TestClient(create_app(layout))
    resp = client.get("/graph", params={"root": enc_id})
    payload = resp.json()

    names = [a["name"] for a in payload["ancestors"]]
    ids = [a["id"] for a in payload["ancestors"]]
    assert names == ["baselines", "Net"]  # top-down order
    assert ids == [baselines_id, net_id]


def test_get_graph_root_at_leaf_is_empty_view(tmp_path: Path) -> None:
    """The inside of a leaf is empty: no nodes, no edges, no boundary. The
    crumb still resolves via root_info/ancestors (deep links land here; the
    UI itself only drills into child_count > 0)."""
    layout = _seed_project(tmp_path)
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")

    client = TestClient(create_app(layout))
    resp = client.get("/graph", params={"root": enc_id})
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["root"] == enc_id
    assert payload["root_info"]["name"] == "enc"
    assert payload["nodes"] == []
    assert payload["edges"] == []
    assert payload["boundary_edges"] == []
    assert [a["name"] for a in payload["ancestors"]] == ["baselines", "Net"]


def test_get_graph_boundary_edge_projects_out_of_view_flow(tmp_path: Path) -> None:
    """§12.4: a port-bearing edge from a node inside the view to one outside
    lands in boundary_edges, with the far endpoint described in external_nodes
    and its port riding along in `ports` for labelling. Contains edges from
    the root never qualify."""
    layout = _seed_project(tmp_path)
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")
    dec_id = next(n.id for n in iter_nodes(layout) if n.name == "dec")

    # Grow a child inside enc whose output feeds dec (outside enc's view).
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="module", name="inner", parent=enc_id, attrs={})],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    inner_id = next(n.id for n in iter_nodes(layout) if n.name == "inner")
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreatePortOp(node=inner_id, name="out0", direction="out", port_type="tensor"),
                CreatePortOp(node=dec_id, name="in_b", direction="in", port_type="tensor"),
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    inner_out = find_port(layout, inner_id, "out0")
    dec_in = find_port(layout, dec_id, "in_b")
    assert inner_out is not None and dec_in is not None
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateEdgeOp(type="data_flow", source=inner_out.id, target=dec_in.id, attrs={}),
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )

    client = TestClient(create_app(layout))
    resp = client.get("/graph", params={"root": enc_id})
    assert resp.status_code == 200
    payload = resp.json()

    assert [n["name"] for n in payload["nodes"]] == ["inner"]
    assert payload["edges"] == []

    assert len(payload["boundary_edges"]) == 1
    flow = payload["boundary_edges"][0]
    assert flow["type"] == "data_flow"
    assert flow["src"] == inner_id and flow["dst"] == dec_id
    assert {x["name"] for x in payload["external_nodes"]} == {"dec"}

    # The outside port of the boundary data_flow rides along in `ports`, so
    # the frontend can label the far endpoint (dec's in-port) instead of '?'.
    port_ids = {p["id"] for p in payload["ports"]}
    assert flow["dst_port"] in port_ids


def test_get_graph_root_own_ports_ride_in_ports(tmp_path: Path) -> None:
    """The root's own ports are the subgraph's declared IO — they ride in
    `ports` (frontend renders them as the view's input/output brackets) even
    though the root itself is not among nodes."""
    layout = _seed_project(tmp_path)
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreatePortOp(node=net_id, name="x", direction="in", port_type="tensor")],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )

    client = TestClient(create_app(layout))
    payload = client.get("/graph", params={"root": net_id}).json()
    root_ports = [p for p in payload["ports"] if p["node_id"] == net_id]
    assert [p["name"] for p in root_ports] == ["x"]
    assert all(n["id"] != net_id for n in payload["nodes"])


def test_tunnel_edge_projects_into_child_view_not_parent_boundary(
    tmp_path: Path,
) -> None:
    """An importer tunnel edge (a container's own port diving into a
    descendant, e.g. ``A.in -> B.in`` with B a child of A) is A's internal
    detail: it must project as the bracket of A's own view, never as a
    boundary edge of the view A sits in. Otherwise every parent view is
    littered with its children's inner wiring."""
    layout = _seed_project(tmp_path)
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")
    # A (child of Net) contains B; A.in tunnels one level into B.in.
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="module", name="A", parent=net_id, attrs={})],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    a_id = next(n.id for n in iter_nodes(layout) if n.name == "A")
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(type="module", name="B", parent=a_id, attrs={}),
                CreatePortOp(node=a_id, name="in", direction="in", port_type="tensor"),
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    b_id = next(n.id for n in iter_nodes(layout) if n.name == "B")
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreatePortOp(node=b_id, name="in", direction="in", port_type="tensor")],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    a_in = find_port(layout, a_id, "in")
    b_in = find_port(layout, b_id, "in")
    assert a_in is not None and b_in is not None
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateEdgeOp(type="data_flow", source=a_in.id, target=b_in.id, attrs={})],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )

    client = TestClient(create_app(layout))
    # Viewing Net: the A→B tunnel is A's inner wiring, not Net's boundary.
    net_view = client.get("/graph", params={"root": net_id}).json()
    assert net_view["boundary_edges"] == []
    # Viewing A: the same edge is A's in-bracket feeding B, so it lands in
    # boundary_edges with the root (A) as the outside endpoint.
    a_view = client.get("/graph", params={"root": a_id}).json()
    assert len(a_view["boundary_edges"]) == 1
    assert a_view["boundary_edges"][0]["src"] == a_id


def test_get_graph_top_level_has_no_boundary_edges(tmp_path: Path) -> None:
    """At top-level there is no outside, so boundary_edges must stay empty
    even if cross-cutting edges exist elsewhere."""
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))
    resp = client.get("/graph")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["root"] is None
    assert payload["boundary_edges"] == []
    assert payload["external_nodes"] == []


def test_get_graph_unknown_root_404(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))
    resp = client.get("/graph", params={"root": "nod_does_not_exist"})
    assert resp.status_code == 404


def test_graph_payload_exposes_capabilities_affordances_and_unknown_profiles(
    tmp_path: Path,
) -> None:
    layout = _seed_project(tmp_path)
    nodes = {node.name: node for node in iter_nodes(layout)}
    save_node(
        layout,
        nodes["dec"].model_copy(update={"type": "uninstalled.domain"}),
    )
    client = TestClient(create_app(layout))

    payload = client.get("/graph", params={"root": nodes["Net"].id}).json()
    by_name = {node["name"]: node for node in payload["nodes"]}

    encoder = by_name["enc"]
    assert set(encoder["capabilities"]) >= {
        "contextualizable",
        "deletable",
        "renamable",
    }
    assert not encoder["unknown_profile"]
    assert {item["id"] for item in encoder["affordances"]} == {
        "node.rename",
        "node.delete",
    }
    assert all(item["enabled"] for item in encoder["affordances"])

    unknown = by_name["dec"]
    assert unknown["id"] == nodes["dec"].id
    assert unknown["type"] == "uninstalled.domain"
    assert unknown["attrs"] == nodes["dec"].attrs
    assert unknown["capabilities"] == []
    assert unknown["unknown_profile"]
    assert unknown["affordances"] == []

    for edge in payload["edges"]:
        assert set(edge) >= {"capabilities", "unknown_profile", "affordances"}
    for port in payload["ports"]:
        assert set(port) >= {"capabilities", "unknown_profile", "affordances"}
    assert set(payload["root_info"]) >= {
        "capabilities",
        "unknown_profile",
        "affordances",
    }


def test_event_stream_emits_commit_for_new_event(tmp_path: Path) -> None:
    """Drive _event_stream directly: snapshot graph_version, apply_patch, then
    pull the next commit frame. Verifies _affected() extraction (event_id +
    affected nodes/edges) without the HTTP transport's buffering quirks."""
    import asyncio
    import contextlib
    import json as _json
    from typing import cast

    from simulanka.server.app import _event_stream

    layout = _seed_project(tmp_path)
    baselines = next(n for n in iter_nodes(layout) if n.name == "baselines")

    class FakeRequest:
        def __init__(self) -> None:
            self.disconnect = False

        async def is_disconnected(self) -> bool:
            return self.disconnect

    async def drive() -> tuple[dict[str, object], dict[str, object]]:
        req = FakeRequest()
        # Cast: _event_stream expects fastapi.Request; the only attribute it
        # touches is is_disconnected, which FakeRequest implements.
        gen = _event_stream(layout, cast(Any, req))
        ready_raw = await gen.__anext__()
        # apply_patch synchronously between yields; the poll loop will pick it
        # up on its next tick.
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreateNodeOp(type="model", name="Net2", parent=baselines.id, attrs={})],
                actor="test",
                base_graph_version=load_manifest(layout).graph_version,
            ),
        )
        commit_raw = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        req.disconnect = True
        # Drain to let the generator return cleanly.
        with contextlib.suppress(StopAsyncIteration, asyncio.TimeoutError):
            await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        return _parse_sse(ready_raw), _parse_sse(commit_raw)

    def _parse_sse(raw: bytes) -> dict[str, object]:
        out: dict[str, object] = {}
        for line in raw.decode("utf-8").splitlines():
            if line.startswith("event: "):
                out["_name"] = line[len("event: "):]
            elif line.startswith("data: "):
                out.update(_json.loads(line[len("data: "):]))
        return out

    ready, commit = asyncio.run(drive())
    assert ready["_name"] == "ready"
    assert isinstance(ready["graph_version"], int)

    assert commit["_name"] == "commit"
    assert commit["actor"] == "test"
    assert isinstance(commit["event_id"], str)
    # CreateNodeOp dual-writes a contains edge: the new node id and its parent
    # both appear in affected nodes, plus one edge.
    nodes = cast(list[str], commit["nodes"])
    edges = cast(list[str], commit["edges"])
    new_net2 = next(n.id for n in iter_nodes(layout) if n.name == "Net2")
    assert new_net2 in nodes
    assert baselines.id in nodes
    assert len(edges) >= 1


def test_positions_round_trip(tmp_path: Path) -> None:
    """POST a delta for one root, GET sees it; second POST under a different
    root coexists without overwriting the first."""
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))

    # Empty to start.
    resp = client.get("/ui/positions")
    assert resp.status_code == 200
    assert resp.json() == {}

    resp = client.post("/ui/positions/top", json={"nod_one": [120.5, 80]})
    assert resp.status_code == 200

    resp = client.post(
        "/ui/positions/nod_root",
        json={"nod_two": [40, 200], "nod_three": [380, 200]},
    )
    assert resp.status_code == 200

    payload = client.get("/ui/positions").json()
    assert payload == {
        "top": {"nod_one": [120.5, 80]},
        "nod_root": {"nod_two": [40, 200], "nod_three": [380, 200]},
    }

    # Partial update merges, doesn't replace.
    client.post("/ui/positions/top", json={"nod_one": [10, 10]})
    payload = client.get("/ui/positions").json()
    assert payload["top"] == {"nod_one": [10, 10]}
    assert payload["nod_root"]["nod_two"] == [40, 200]

    # File lives where we expect.
    assert (layout.dot_dir / "ui" / "positions.json").is_file()


def test_positions_reject_malformed(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))

    for bad in (
        {"nid": "not-a-list"},
        {"nid": [1, 2, 3]},
        {"nid": ["nope", 4]},
    ):
        resp = client.post("/ui/positions/top", json=bad)
        assert resp.status_code == 422, bad

    # No partial write must have happened.
    assert client.get("/ui/positions").json() == {}


def _port_ids(layout: ProjectLayout) -> tuple[str, str]:
    """(enc.out0, dec.in0) port ids of the seeded project."""
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")
    dec_id = next(n.id for n in iter_nodes(layout) if n.name == "dec")
    enc_out = find_port(layout, enc_id, "out0")
    dec_in = find_port(layout, dec_id, "in0")
    assert enc_out is not None and dec_in is not None
    return enc_out.id, dec_in.id


def test_create_user_edge(tmp_path: Path) -> None:
    """POST /edge persists a data_flow edge stamped source=user with the
    draw-time shape verdict."""
    layout = _seed_project(tmp_path)
    # Drop the seeded edge first so we can re-draw it cleanly via the API.
    seeded = next(e for e in iter_edges(layout) if e.type == "data_flow")
    apply_patch(
        layout,
        PatchIntent(
            ops=[DeleteEdgeOp(edge=seeded.id)],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    client = TestClient(create_app(layout))
    enc_out, dec_in = _port_ids(layout)

    resp = client.post(
        "/edge",
        json={"src_port": enc_out, "dst_port": dec_in, "shape_check": "mismatch"},
    )
    assert resp.status_code == 200, resp.text
    edge_id = resp.json()["edge_id"]
    edge = load_edge(layout, edge_id)
    assert edge.type == "data_flow"
    assert edge.attrs == {"source": "user", "shape_check": "mismatch"}
    assert edge.source_port_id == enc_out
    assert edge.target_port_id == dec_in


def test_create_user_edge_wrong_direction_422(tmp_path: Path) -> None:
    """out→in is the only hard gate; feeding two same-direction ports is 422."""
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))
    enc_out, _ = _port_ids(layout)
    # enc.out0 → enc.out0 violates the data_flow direction rule.
    resp = client.post("/edge", json={"src_port": enc_out, "dst_port": enc_out})
    assert resp.status_code == 422


def test_create_user_edge_missing_fields_422(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))
    resp = client.post("/edge", json={"src_port": "prt_x"})
    assert resp.status_code == 422


def test_create_user_edge_unknown_port_422(tmp_path: Path) -> None:
    """A stale client referencing a vanished port id gets a clean 422, not a
    500 from an uncaught resolver ValueError."""
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))
    _, dec_in = _port_ids(layout)
    resp = client.post("/edge", json={"src_port": "prt_gone", "dst_port": dec_in})
    assert resp.status_code == 422


def test_delete_edge_endpoint(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    edge = next(e for e in iter_edges(layout) if e.type == "data_flow")
    client = TestClient(create_app(layout))

    resp = client.delete(f"/edge/{edge.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == [edge.id]
    assert not edge_exists(layout, edge.id)


def test_delete_edge_endpoint_refuses_contains_422(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    contains = next(e for e in iter_edges(layout) if e.type == "contains")
    client = TestClient(create_app(layout))
    resp = client.delete(f"/edge/{contains.id}")
    assert resp.status_code == 422
    assert edge_exists(layout, contains.id)


# --- canvas authoring: POST /node, rename, templates -------------------------


def test_post_node_creates_node_with_ports(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")
    client = TestClient(create_app(layout))

    resp = client.post(
        "/node",
        json={
            "type": "module",
            "name": "conv1",
            "parent": net_id,
            "attrs": {"class_name": "Conv2d", "class_module": "torch.nn"},
            "ports": [
                {"name": "input", "direction": "in", "port_type": "tensor"},
                {"name": "output", "direction": "out", "port_type": "tensor"},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["name"] == "conv1"
    assert len(out["port_ids"]) == 2

    node = next(n for n in iter_nodes(layout) if n.id == out["node_id"])
    assert node.parent_id == net_id
    assert node.attrs["class_name"] == "Conv2d"

    # The new node shows up in its parent's view, ports wired.
    payload = client.get("/graph", params={"root": net_id}).json()
    by_name = {n["name"]: n for n in payload["nodes"]}
    assert set(by_name["conv1"]["ports"]) == set(out["port_ids"])


def test_post_node_sibling_collision_gets_suffix(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")
    client = TestClient(create_app(layout))

    # "enc" already lives under Net — the menu drop must not 422.
    resp = client.post("/node", json={"type": "module", "name": "enc", "parent": net_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "enc_2"


def test_post_node_validation(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))

    assert client.post("/node", json={"name": "x"}).status_code == 422
    assert client.post("/node", json={"type": "module"}).status_code == 422
    assert (
        client.post(
            "/node", json={"type": "module", "name": "x", "parent": "nod_missing"}
        ).status_code
        == 404
    )
    resp = client.post(
        "/node",
        json={
            "type": "module",
            "name": "x",
            "ports": [{"name": "p", "direction": "sideways"}],
        },
    )
    assert resp.status_code == 422


def test_rename_node_endpoint(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")
    client = TestClient(create_app(layout))

    resp = client.post(f"/node/{enc_id}/rename", json={"new_name": "encoder"})
    assert resp.status_code == 200, resp.text
    assert next(n.name for n in iter_nodes(layout) if n.id == enc_id) == "encoder"

    # Sibling conflict → kernel 422.
    assert (
        client.post(f"/node/{enc_id}/rename", json={"new_name": "dec"}).status_code == 422
    )
    # file/directory names are bound to fs_path — refused here.
    dir_id = next(n.id for n in iter_nodes(layout) if n.type == "directory")
    assert (
        client.post(f"/node/{dir_id}/rename", json={"new_name": "other"}).status_code == 422
    )
    assert client.post("/node/nod_missing/rename", json={"new_name": "x"}).status_code == 404


def test_delete_node_endpoint(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")
    client = TestClient(create_app(layout))

    # Leaf module: gone, along with its ports and the enc→dec data_flow edge.
    resp = client.delete(f"/node/{enc_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == [enc_id]
    assert all(n.id != enc_id for n in iter_nodes(layout))
    assert all(e.type != "data_flow" for e in iter_edges(layout))

    # Non-empty container → kernel 422 (empty it first).
    resp = client.delete(f"/node/{net_id}")
    assert resp.status_code == 422
    assert "children" in resp.json()["detail"]

    # Outside the sketch domain → policy 422; unknown id → 404.
    dir_id = next(n.id for n in iter_nodes(layout) if n.type == "directory")
    assert client.delete(f"/node/{dir_id}").status_code == 422
    assert client.delete("/node/nod_missing").status_code == 404


def test_node_policies_follow_injected_profile_capabilities(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    registry = Registry.build(
        version=2,
        packages=(*BUILTIN_PACKAGES, SOFTWARE_SERVICE_PACKAGE),
    )
    client = TestClient(create_app(layout, registry=registry))
    parent_id = next(node.id for node in iter_nodes(layout) if node.name == "src")

    created = client.post(
        "/node",
        json={
            "type": "software.service",
            "name": "api",
            "parent": parent_id,
            "attrs": {"runtime": "python"},
        },
    )
    assert created.status_code == 200, created.text
    node_id = created.json()["node_id"]

    renamed = client.post(f"/node/{node_id}/rename", json={"new_name": "gateway"})
    assert renamed.status_code == 200, renamed.text
    deleted = client.delete(f"/node/{node_id}")
    assert deleted.status_code == 200, deleted.text

    directory_id = next(node.id for node in iter_nodes(layout) if node.name == "docs")
    rename_denied = client.post(
        f"/node/{directory_id}/rename",
        json={"new_name": "documents"},
    )
    assert rename_denied.status_code == 422
    assert rename_denied.json()["detail"]["reason_code"] == "missing_capability"
    assert "renamable" in rename_denied.json()["detail"]["reason"]
    delete_denied = client.delete(f"/node/{directory_id}")
    assert delete_denied.status_code == 422
    assert delete_denied.json()["detail"]["reason_code"] == "missing_capability"
    assert "deletable" in delete_denied.json()["detail"]["reason"]


def test_action_endpoints_revalidate_current_state_and_source_policy(
    tmp_path: Path,
) -> None:
    layout = _seed_project(tmp_path)
    nodes = {node.name: node for node in iter_nodes(layout)}
    client = TestClient(create_app(layout))

    # The action is initially available, then a stale rename is rejected from
    # current graph state after another writer locks the entity.
    first = client.post(
        f"/node/{nodes['enc'].id}/rename",
        json={"new_name": "encoder"},
    )
    assert first.status_code == 200, first.text
    apply_patch_now(
        layout,
        ops=[
            UpdateAttrsOp(
                target=nodes["enc"].id,
                attrs={"locked": True, "lock_reason": "该节点正在运行，暂不可重命名"},
            )
        ],
        actor="test",
        note="simulate state change after menu discovery",
    )
    stale = client.post(
        f"/node/{nodes['enc'].id}/rename",
        json={"new_name": "stale-name"},
    )
    assert stale.status_code == 422
    assert stale.json()["detail"] == {
        "action": "node.rename",
        "reason": "该节点正在运行，暂不可重命名",
        "reason_code": "state_locked",
    }

    # A structurally deletable Profile remains disabled when its source marks
    # the current entity as an immutable projection.
    apply_patch_now(
        layout,
        ops=[
            UpdateAttrsOp(
                target=nodes["dec"].id,
                attrs={"source": "projection", "immutable": True},
            )
        ],
        actor="test",
        note="simulate immutable projection",
    )
    projected = client.delete(f"/node/{nodes['dec'].id}")
    assert projected.status_code == 422
    assert projected.json()["detail"]["reason_code"] == "source_read_only"
    assert "projection" in projected.json()["detail"]["reason"]


def test_registry_descriptor_endpoint_uses_injected_registry(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    registry = Registry.build(
        version=2,
        packages=(*BUILTIN_PACKAGES, SOFTWARE_SERVICE_PACKAGE),
    )
    response = TestClient(create_app(layout, registry=registry)).get("/registry")

    assert response.status_code == 200
    descriptor = response.json()
    assert descriptor["version"] == registry.version
    assert descriptor["digest"] == registry.descriptor_digest
    assert set(descriptor) == {
        "version",
        "digest",
        "packages",
        "capabilities",
        "node_profiles",
        "edge_profiles",
        "port_types",
        "presentations",
        "templates",
        "actions",
        "aliases",
    }
    assert "software.service" in {
        profile["key"] for profile in descriptor["node_profiles"]
    }
    assert "software.depends_on" in {
        profile["key"] for profile in descriptor["edge_profiles"]
    }
    assert "software.http-service" in {
        template["key"] for template in descriptor["templates"]
    }
    assert {action["id"] for action in descriptor["actions"]} >= {
        "node.rename",
        "node.delete",
    }


def test_graph_affordances_cover_disabled_non_research_extension(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path).layout
    registry = Registry.build(
        version=2,
        packages=(*BUILTIN_PACKAGES, SOFTWARE_SERVICE_PACKAGE),
    )
    client = TestClient(create_app(layout, registry=registry))
    parent_id = next(node.id for node in iter_nodes(layout) if node.name == "src")
    created = client.post(
        "/node",
        json={
            "type": "software.service",
            "name": "api",
            "parent": parent_id,
            "attrs": {
                "runtime": "python",
                "locked": True,
                "lock_reason": "服务部署中，暂不可修改",
            },
        },
    )
    assert created.status_code == 200, created.text

    payload = client.get("/graph", params={"root": parent_id}).json()
    service = next(node for node in payload["nodes"] if node["id"] == created.json()["node_id"])
    assert service["type"] == "software.service"
    assert not service["unknown_profile"]
    assert set(service["capabilities"]) >= {
        "contextualizable",
        "renamable",
        "deletable",
        "deployable",
    }
    affordances = {item["id"]: item for item in service["affordances"]}
    assert set(affordances) == {"node.rename", "node.delete"}
    assert all(not item["enabled"] for item in affordances.values())
    assert {item["reason_code"] for item in affordances.values()} == {"state_locked"}
    assert {item["reason"] for item in affordances.values()} == {
        "服务部署中，暂不可修改"
    }


def test_graph_payload_identifies_its_registry_descriptor(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    registry = Registry.build(
        version=2,
        packages=(*BUILTIN_PACKAGES, SOFTWARE_SERVICE_PACKAGE),
    )
    client = TestClient(create_app(layout, registry=registry))

    graph = client.get("/graph").json()
    descriptor = client.get("/registry").json()
    assert graph["registry_digest"] == registry.descriptor_digest
    assert graph["registry_digest"] == descriptor["digest"]


def test_templates_roundtrip(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))

    assert client.get("/ui/templates").json() == {}

    resp = client.post(
        "/ui/templates",
        json={
            "name": "MyBlock",
            "type": "module",
            "category": "blocks",
            "attrs": {"class_name": "MyBlock"},
            "ports": [{"name": "input", "direction": "in"}],
        },
    )
    assert resp.status_code == 200, resp.text
    saved = client.get("/ui/templates").json()
    assert saved["MyBlock"]["type"] == "module"
    assert saved["MyBlock"]["category"] == "blocks"
    assert saved["MyBlock"]["ports"][0]["port_type"] == "any"  # default rides in

    # Overwrite in place; omitted category falls back to "custom".
    client.post("/ui/templates", json={"name": "MyBlock", "type": "module"})
    assert client.get("/ui/templates").json()["MyBlock"]["category"] == "custom"

    assert client.delete("/ui/templates/MyBlock").status_code == 200
    assert client.get("/ui/templates").json() == {}
    assert client.delete("/ui/templates/MyBlock").status_code == 404

    assert client.post("/ui/templates", json={"type": "module"}).status_code == 422


def test_cors_allows_dev_origin(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))
    resp = client.get(
        "/graph",
        headers={"Origin": "http://localhost:5173"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


# --- §13.6 verify-discuss endpoints ----------------------------------------


def _seed_ghost_edge(layout: ProjectLayout) -> str:
    """Lay a second out-port + ghost data_flow edge (dec.out → enc has no in,
    so reuse enc_out → dec_in pair via fresh ports) and return its edge id."""
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")
    dec_id = next(n.id for n in iter_nodes(layout) if n.name == "dec")
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreatePortOp(node=enc_id, name="out1", direction="out", port_type="tensor"),
                CreatePortOp(node=dec_id, name="in1", direction="in", port_type="tensor"),
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    enc_out = find_port(layout, enc_id, "out1")
    dec_in = find_port(layout, dec_id, "in1")
    assert enc_out is not None and dec_in is not None
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateEdgeOp(
                    type="data_flow",
                    source=enc_out.id,
                    target=dec_in.id,
                    attrs={
                        "source": "agent",
                        "status": "proposed",
                        "verdict": "unconfirmed",
                        "citation": "x = self.dec(self.enc(x))",
                    },
                ),
            ],
            actor="agent:propose",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    return receipt.edges[0]


def test_reject_ghost_keeps_it_proposed_and_queued(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    ghost_id = _seed_ghost_edge(layout)
    client = TestClient(create_app(layout))

    resp = client.post(
        f"/edge/{ghost_id}/verdict",
        json={"verdict": "wrong", "note": "skip 分支不经过 dec"},
    )
    assert resp.status_code == 200, resp.text

    edge = load_edge(layout, ghost_id)
    assert edge.attrs["verdict"] == "wrong"
    assert edge.attrs["verdict_by"] == "user"
    assert edge.attrs["verdict_note"] == "skip 分支不经过 dec"
    assert edge.attrs["status"] == "proposed"  # NOT deleted
    assert edge.attrs["citation"]  # agent evidence preserved

    dis = client.get("/disagreements").json()["disagreements"]
    assert [d["id"] for d in dis] == [ghost_id]
    assert dis[0]["reasons"] == ["user_rejected_ghost"]
    # Endpoint names ride along — the panel must not fall back to raw node
    # ids when the disagreement lives outside the current view.
    assert dis[0]["src_name"] == "enc"
    assert dis[0]["dst_name"] == "dec"


def test_verdict_requires_note(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    ghost_id = _seed_ghost_edge(layout)
    client = TestClient(create_app(layout))

    for body in (
        {"verdict": "wrong"},
        {"verdict": "wrong", "note": "   "},
        {"verdict": "nonsense", "note": "x"},
    ):
        resp = client.post(f"/edge/{ghost_id}/verdict", json=body)
        assert resp.status_code == 422, body
    assert load_edge(layout, ghost_id).attrs["verdict"] == "unconfirmed"


def test_verdict_404_unknown_and_422_contains(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    contains = next(e for e in iter_edges(layout) if e.type == "contains")
    client = TestClient(create_app(layout))

    ok_body = {"verdict": "wrong", "note": "x"}
    assert client.post("/edge/edg_nope/verdict", json=ok_body).status_code == 404
    assert client.post(f"/edge/{contains.id}/verdict", json=ok_body).status_code == 422


def test_accept_ghost(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    ghost_id = _seed_ghost_edge(layout)
    client = TestClient(create_app(layout))

    resp = client.post(f"/edge/{ghost_id}/accept")
    assert resp.status_code == 200, resp.text
    edge = load_edge(layout, ghost_id)
    assert edge.attrs["status"] == "accepted"
    assert edge.attrs["verdict"] == "correct"
    assert edge.attrs["verdict_by"] == "user"
    assert client.get("/disagreements").json()["disagreements"] == []


def test_accept_non_ghost_rejected(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    user_edge = next(e for e in iter_edges(layout) if e.type == "data_flow")
    client = TestClient(create_app(layout))
    assert client.post(f"/edge/{user_edge.id}/accept").status_code == 422


def test_disagreements_agent_flagged_and_disputed(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    user_edge = next(e for e in iter_edges(layout) if e.type == "data_flow")
    ghost_id = _seed_ghost_edge(layout)

    # Simulate the agent verify pass: human-drawn edge ruled uncertain, ghost disputed.
    from simulanka.kernel.intent import UpdateAttrsOp
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                UpdateAttrsOp(
                    target=user_edge.id,
                    attrs={"source": "user", "verdict": "uncertain", "verdict_by": "agent"},
                ),
                UpdateAttrsOp(target=ghost_id, attrs={"verdict": "disputed"}),
            ],
            actor="agent:verify",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    client = TestClient(create_app(layout))
    dis = {d["id"]: d["reasons"] for d in client.get("/disagreements").json()["disagreements"]}
    assert dis[user_edge.id] == ["agent_flagged_user_edge"]
    assert dis[ghost_id] == ["disputed"]


def test_discuss_toggle(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    user_edge = next(e for e in iter_edges(layout) if e.type == "data_flow")
    client = TestClient(create_app(layout))

    assert client.post(f"/edge/{user_edge.id}/discuss").status_code == 200
    dis = client.get("/disagreements").json()["disagreements"]
    assert [d["id"] for d in dis] == [user_edge.id]
    assert dis[0]["reasons"] == ["manual"]

    assert (
        client.post(f"/edge/{user_edge.id}/discuss", json={"discuss": False}).status_code
        == 200
    )
    assert client.get("/disagreements").json()["disagreements"] == []


def test_cors_preflight_allows_delete(tmp_path: Path) -> None:
    """Direct-browser mode (no vite proxy) needs DELETE in the CORS allowlist
    for `DELETE /edge/{id}` to survive preflight."""
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))
    resp = client.options(
        "/edge/edg_anything",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert resp.status_code == 200
    assert "DELETE" in resp.headers["access-control-allow-methods"]
