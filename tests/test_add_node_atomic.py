from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import CreateNodeOp, CreatePortOp, PatchIntent
from simulanka.kernel.manifest import load_manifest
from simulanka.kernel.validator import ValidationError
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.server.app import create_app
from simulanka.storage.entity_store import iter_nodes, iter_ports


def _seed_model(tmp_path: Path) -> tuple[ProjectLayout, str]:
    layout = init_project(tmp_path).layout
    baselines = next(node for node in iter_nodes(layout) if node.name == "baselines")
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="model", name="AtomicNet", parent=baselines.id)],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    model_id = next(
        node.id
        for node in iter_nodes(layout)
        if node.name == "AtomicNet" and node.type == "model"
    )
    return layout, model_id


def test_create_port_can_target_pending_node_ref(tmp_path: Path) -> None:
    layout, model_id = _seed_model(tmp_path)
    before = load_manifest(layout).graph_version

    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(
                    type="module",
                    name="conv",
                    parent=model_id,
                    ref="new_node",
                ),
                CreatePortOp(
                    node="@new_node",
                    name="input",
                    direction="in",
                    port_type="tensor",
                ),
                CreatePortOp(
                    node="@new_node",
                    name="output",
                    direction="out",
                    port_type="tensor",
                ),
            ],
            actor="test",
            base_graph_version=before,
        ),
    )

    assert receipt.graph_version == before + 1
    assert len(receipt.nodes) == 1
    assert len(receipt.ports) == 2
    node_id = receipt.nodes[0]
    assert {port.node_id for port in iter_ports(layout) if port.id in receipt.ports} == {node_id}


def test_invalid_later_port_aborts_pending_node_and_all_ports(tmp_path: Path) -> None:
    layout, model_id = _seed_model(tmp_path)
    before_version = load_manifest(layout).graph_version
    before_nodes = {node.id for node in iter_nodes(layout)}
    before_ports = {port.id for port in iter_ports(layout)}

    with pytest.raises(ValidationError, match="Unknown port_type"):
        apply_patch(
            layout,
            PatchIntent(
                ops=[
                    CreateNodeOp(
                        type="module",
                        name="must_not_survive",
                        parent=model_id,
                        ref="new_node",
                    ),
                    CreatePortOp(
                        node="@new_node",
                        name="input",
                        direction="in",
                        port_type="tensor",
                    ),
                    CreatePortOp(
                        node="@new_node",
                        name="broken",
                        direction="out",
                        port_type="definitely-not-registered",
                    ),
                ],
                actor="test",
                base_graph_version=before_version,
            ),
        )

    assert load_manifest(layout).graph_version == before_version
    assert {node.id for node in iter_nodes(layout)} == before_nodes
    assert {port.id for port in iter_ports(layout)} == before_ports
    assert all(node.name != "must_not_survive" for node in iter_nodes(layout))


def test_post_node_with_ports_advances_graph_once(tmp_path: Path) -> None:
    layout, model_id = _seed_model(tmp_path)
    client = TestClient(create_app(layout))
    before = load_manifest(layout).graph_version

    response = client.post(
        "/node",
        json={
            "type": "module",
            "name": "atomic",
            "parent": model_id,
            "ports": [
                {"name": "input", "direction": "in", "port_type": "tensor"},
                {"name": "output", "direction": "out", "port_type": "tensor"},
            ],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["graph_version"] == before + 1
    assert load_manifest(layout).graph_version == before + 1
    assert len(payload["port_ids"]) == 2
    assert {
        port.node_id
        for port in iter_ports(layout)
        if port.id in set(payload["port_ids"])
    } == {payload["node_id"]}


def test_post_node_invalid_port_leaves_no_partial_node(tmp_path: Path) -> None:
    layout, model_id = _seed_model(tmp_path)
    client = TestClient(create_app(layout))
    before_version = load_manifest(layout).graph_version
    before_nodes = {node.id for node in iter_nodes(layout)}
    before_ports = {port.id for port in iter_ports(layout)}

    response = client.post(
        "/node",
        json={
            "type": "module",
            "name": "must_not_survive",
            "parent": model_id,
            "ports": [
                {"name": "input", "direction": "in", "port_type": "tensor"},
                {
                    "name": "broken",
                    "direction": "out",
                    "port_type": "definitely-not-registered",
                },
            ],
        },
    )

    assert response.status_code == 422
    assert load_manifest(layout).graph_version == before_version
    assert {node.id for node in iter_nodes(layout)} == before_nodes
    assert {port.id for port in iter_ports(layout)} == before_ports
    assert all(node.name != "must_not_survive" for node in iter_nodes(layout))
