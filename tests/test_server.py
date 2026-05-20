from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    CreatePortOp,
    PatchIntent,
)
from simulanka.kernel.manifest import load_manifest
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.server.app import create_app
from simulanka.storage.entity_store import find_port, iter_nodes


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


def test_get_graph_unknown_root_404(tmp_path: Path) -> None:
    layout = _seed_project(tmp_path)
    client = TestClient(create_app(layout))
    resp = client.get("/graph", params={"root": "nod_does_not_exist"})
    assert resp.status_code == 404


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
