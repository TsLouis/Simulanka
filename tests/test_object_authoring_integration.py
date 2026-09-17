from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.events import iter_events
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.kernel.manifest import load_manifest
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.server.app import _affected, create_app
from simulanka.storage.entity_store import iter_nodes


def _seed_model(layout: ProjectLayout) -> tuple[str, str, str]:
    baselines = next(node for node in iter_nodes(layout) if node.name == "baselines")
    model = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(
                    type="model",
                    name="AuthoringNet",
                    parent=baselines.id,
                    ref="model",
                ),
                CreateNodeOp(
                    type="module",
                    name="source",
                    parent="@model",
                    ref="source",
                ),
                CreateNodeOp(
                    type="module",
                    name="sink",
                    parent="@model",
                    ref="sink",
                ),
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    return model.nodes[0], model.nodes[1], model.nodes[2]


def _graph(client: TestClient, root: str) -> dict[str, object]:
    response = client.get("/graph", params={"root": root})
    assert response.status_code == 200, response.text
    return response.json()


def test_port_authoring_round_trip_projects_owner_for_reload(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    model_id, source_id, _ = _seed_model(layout)
    client = TestClient(create_app(layout))

    created = client.post(
        f"/node/{source_id}/ports",
        json={
            "name": "input",
            "direction": "in",
            "port_type": "tensor",
            "attrs": {"label": "Input"},
        },
    )
    assert created.status_code == 200, created.text
    port_id = created.json()["port_id"]

    create_affected = _affected(list(iter_events(layout))[-1])
    assert port_id in create_affected["ports"]
    assert source_id in create_affected["nodes"]

    payload = _graph(client, model_id)
    source = next(node for node in payload["nodes"] if node["id"] == source_id)
    assert port_id in source["ports"]
    port = next(item for item in payload["ports"] if item["id"] == port_id)
    assert (port["name"], port["side"], port["port_type"]) == (
        "input",
        "in",
        "tensor",
    )

    updated = client.post(
        f"/port/{port_id}/update",
        json={
            "name": "result",
            "direction": "out",
            "port_type": "scalar",
            "attrs": {
                "label": "Result",
                "shape": [2, 4],
                "confidence": "verified",
            },
        },
    )
    assert updated.status_code == 200, updated.text

    update_affected = _affected(list(iter_events(layout))[-1])
    assert port_id in update_affected["ports"]
    assert source_id in update_affected["nodes"]

    payload = _graph(client, model_id)
    port = next(item for item in payload["ports"] if item["id"] == port_id)
    assert (port["name"], port["side"], port["port_type"]) == (
        "result",
        "out",
        "scalar",
    )
    assert port["attrs"] == {
        "label": "Result",
        "shape": [2, 4],
        "confidence": "verified",
    }

    deleted = client.delete(f"/port/{port_id}")
    assert deleted.status_code == 200, deleted.text

    delete_affected = _affected(list(iter_events(layout))[-1])
    assert port_id in delete_affected["ports"]
    assert source_id in delete_affected["nodes"]

    payload = _graph(client, model_id)
    source = next(node for node in payload["nodes"] if node["id"] == source_id)
    assert port_id not in source["ports"]
    assert all(item["id"] != port_id for item in payload["ports"])


def test_edge_disconnect_persists_across_graph_reload(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    model_id, source_id, sink_id = _seed_model(layout)
    client = TestClient(create_app(layout))

    source_port = client.post(
        f"/node/{source_id}/ports",
        json={"name": "out", "direction": "out", "port_type": "tensor"},
    )
    sink_port = client.post(
        f"/node/{sink_id}/ports",
        json={"name": "in", "direction": "in", "port_type": "tensor"},
    )
    assert source_port.status_code == 200, source_port.text
    assert sink_port.status_code == 200, sink_port.text

    edge = client.post(
        "/edge",
        json={
            "src_port": source_port.json()["port_id"],
            "dst_port": sink_port.json()["port_id"],
            "shape_check": "unknown",
        },
    )
    assert edge.status_code == 200, edge.text
    edge_id = edge.json()["edge_id"]
    assert any(item["id"] == edge_id for item in _graph(client, model_id)["edges"])

    disconnected = client.delete(f"/edge/{edge_id}")
    assert disconnected.status_code == 200, disconnected.text
    assert all(item["id"] != edge_id for item in _graph(client, model_id)["edges"])


def test_node_delete_does_not_leave_reload_phantom(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    model_id, _, _ = _seed_model(layout)
    empty = apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="module", name="temporary", parent=model_id)],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    node_id = empty.nodes[0]
    client = TestClient(create_app(layout))

    assert any(item["id"] == node_id for item in _graph(client, model_id)["nodes"])
    deleted = client.delete(f"/node/{node_id}")
    assert deleted.status_code == 200, deleted.text

    affected = _affected(list(iter_events(layout))[-1])
    assert model_id in affected["nodes"]
    assert all(item["id"] != node_id for item in _graph(client, model_id)["nodes"])
