from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    CreatePortOp,
    DeleteEdgeOp,
    PatchIntent,
)
from simulanka.kernel.manifest import load_manifest
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.server.app import create_app
from simulanka.storage.entity_store import (
    edge_exists,
    find_port,
    iter_edges,
    iter_nodes,
    load_edge,
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

    resp = client.get("/graph", params={"depth": 0})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["root"] is None
    # depth=0, no root: top-level directories only — no Net (it lives under baselines).
    types = {n["type"] for n in payload["nodes"]}
    assert types == {"directory"}
    assert all(n["parent_id"] is None for n in payload["nodes"])
    # No root → no ancestor chain.
    assert payload["ancestors"] == []


def test_get_graph_root_depth_1_includes_children(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")

    client = TestClient(create_app(layout))
    resp = client.get("/graph", params={"root": net_id, "depth": 1})
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["root"] == net_id
    names = sorted(n["name"] for n in payload["nodes"])
    assert names == ["Net", "dec", "enc"]

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

    # child_count is the direct-children count; Net has enc+dec, enc/dec are leaves.
    by_name = {n["name"]: n for n in payload["nodes"]}
    assert by_name["Net"]["child_count"] == 2
    assert by_name["enc"]["child_count"] == 0
    assert by_name["dec"]["child_count"] == 0

    # Inbound containment from baselines → Net counts as cross-boundary; data
    # flows between enc and dec are internal.
    assert len(payload["boundary_edges"]) == 1
    incoming = payload["boundary_edges"][0]
    assert incoming["type"] == "contains"
    assert incoming["dst"] == net_id
    assert {x["name"] for x in payload["external_nodes"]} == {"baselines"}


def test_get_graph_ancestors_chain_from_root(tmp_path: Path) -> None:
    """root=enc returns the parent chain `baselines/Net` (top-down). The
    frontend uses this to rebuild crumbs after jump-external or deep-link
    loads with an arbitrary root."""
    layout = _seed_project(tmp_path)
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")
    baselines_id = next(n.id for n in iter_nodes(layout) if n.name == "baselines")

    client = TestClient(create_app(layout))
    resp = client.get("/graph", params={"root": enc_id, "depth": 0})
    payload = resp.json()

    names = [a["name"] for a in payload["ancestors"]]
    ids = [a["id"] for a in payload["ancestors"]]
    assert names == ["baselines", "Net"]  # top-down order
    assert ids == [baselines_id, net_id]


def test_get_graph_root_at_leaf_module_exposes_boundary_edge(tmp_path: Path) -> None:
    """root=enc, depth=0 → only enc is included. Two edges cross the boundary:
    the data_flow enc→dec (out to a sibling) and the contains Net→enc (in from
    the parent). Frontend §12.4 then decides which to project as boundary
    ports — only port-bearing edges qualify."""
    layout = _seed_project(tmp_path)
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")
    dec_id = next(n.id for n in iter_nodes(layout) if n.name == "dec")
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net" and n.type == "model")

    client = TestClient(create_app(layout))
    resp = client.get("/graph", params={"root": enc_id, "depth": 0})
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["root"] == enc_id
    assert [n["name"] for n in payload["nodes"]] == ["enc"]
    assert payload["edges"] == []

    by_type = {e["type"]: e for e in payload["boundary_edges"]}
    assert set(by_type) == {"data_flow", "contains"}

    flow = by_type["data_flow"]
    assert flow["src"] == enc_id and flow["dst"] == dec_id
    assert flow["src_port"] is not None and flow["dst_port"] is not None

    contains = by_type["contains"]
    assert contains["src"] == net_id and contains["dst"] == enc_id

    ext_names = {x["name"] for x in payload["external_nodes"]}
    assert ext_names == {"dec", "Net"}

    # The outside port of the boundary data_flow rides along in `ports`, so
    # the frontend can label the far endpoint (dec's in-port) instead of '?'.
    port_ids = {p["id"] for p in payload["ports"]}
    assert flow["dst_port"] in port_ids


def test_get_graph_top_level_has_no_boundary_edges(tmp_path: Path) -> None:
    """At top-level there is no outside, so boundary_edges must stay empty
    even if cross-cutting edges exist elsewhere."""
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))
    resp = client.get("/graph", params={"depth": 0})
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


def test_cors_allows_dev_origin(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))
    resp = client.get(
        "/graph",
        params={"depth": 0},
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
