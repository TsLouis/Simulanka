from __future__ import annotations

from dataclasses import replace
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
    DeletePortOp,
    PatchIntent,
    UpdatePortOp,
)
from simulanka.kernel.manifest import load_manifest
from simulanka.kernel.validator import ValidationError
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.registry import BUILTIN_PACKAGES, Registry
from simulanka.server.app import create_app
from simulanka.storage.entity_store import (
    edge_exists,
    find_port,
    iter_edges,
    iter_nodes,
    load_port,
    port_exists,
)


def _seed_ports(layout: ProjectLayout) -> tuple[str, str, str, str, str]:
    baselines = next(node for node in iter_nodes(layout) if node.name == "baselines")
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(
                    type="model",
                    name="AuthoringNet",
                    parent=baselines.id,
                    ref="model",
                ),
                CreateNodeOp(type="module", name="source", parent="@model", ref="source"),
                CreateNodeOp(type="module", name="sink", parent="@model", ref="sink"),
                CreatePortOp(
                    node="@source",
                    name="output",
                    direction="out",
                    port_type="tensor",
                ),
                CreatePortOp(
                    node="@sink",
                    name="input",
                    direction="in",
                    port_type="tensor",
                ),
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    model_id, source_id, sink_id = receipt.nodes
    source_port_id, sink_port_id = receipt.ports
    edge_receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateEdgeOp(
                    type="data_flow",
                    source=source_port_id,
                    target=sink_port_id,
                )
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    return model_id, source_id, sink_id, source_port_id, edge_receipt.edges[0]


def test_kernel_updates_and_deletes_unconnected_port_atomically(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    model_id, _, _, _, _ = _seed_ports(layout)
    created = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreatePortOp(
                    node=model_id,
                    name="free",
                    direction="in",
                    port_type="tensor",
                    attrs={"confidence": "inferred"},
                )
            ],
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )
    port_id = created.ports[0]
    before_update = load_manifest(layout).graph_version

    for invalid_op, error in (
        (UpdatePortOp(port=port_id, port_type="unknown"), "Unknown port_type"),
        (
            UpdatePortOp(port=port_id, attrs={"arbitrary": True}),
            "explicitly editable",
        ),
    ):
        with pytest.raises(ValidationError, match=error):
            apply_patch(
                layout,
                PatchIntent(
                    ops=[invalid_op],
                    actor="test",
                    base_graph_version=before_update,
                ),
            )
        assert load_manifest(layout).graph_version == before_update

    updated = apply_patch(
        layout,
        PatchIntent(
            ops=[
                UpdatePortOp(
                    port=port_id,
                    name="renamed",
                    direction="out",
                    port_type="scalar",
                    attrs={"label": "result", "shape": [1, 8]},
                )
            ],
            actor="test",
            base_graph_version=before_update,
        ),
    )

    assert updated.graph_version == before_update + 1
    assert updated.updated_ports == [port_id]
    port = load_port(layout, port_id)
    assert (port.name, port.direction, port.port_type) == ("renamed", "out", "scalar")
    assert port.attrs == {
        "confidence": "inferred",
        "label": "result",
        "shape": [1, 8],
    }

    before_delete = load_manifest(layout).graph_version
    deleted = apply_patch(
        layout,
        PatchIntent(
            ops=[DeletePortOp(port=port_id)],
            actor="test",
            base_graph_version=before_delete,
        ),
    )
    assert deleted.graph_version == before_delete + 1
    assert deleted.deleted_ports == [port_id]
    assert not port_exists(layout, port_id)


@pytest.mark.parametrize(
    "op, error",
    [
        (UpdatePortOp(port="prt_missing", name="x"), "No port"),
        (DeletePortOp(port="prt_missing"), "No port"),
    ],
)
def test_invalid_port_ops_leave_graph_version_unchanged(
    tmp_path: Path,
    op: UpdatePortOp | DeletePortOp,
    error: str,
) -> None:
    layout = init_project(tmp_path).layout
    before = load_manifest(layout).graph_version

    with pytest.raises(ValidationError, match=error):
        apply_patch(
            layout,
            PatchIntent(
                ops=[op],
                actor="test",
                base_graph_version=before,
            ),
        )

    assert load_manifest(layout).graph_version == before


def test_kernel_rejects_connected_topology_edits_and_delete_without_cascade(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path).layout
    _, _, _, port_id, edge_id = _seed_ports(layout)
    before = load_manifest(layout).graph_version

    for op in (
        UpdatePortOp(port=port_id, direction="in"),
        UpdatePortOp(port=port_id, port_type="scalar"),
        DeletePortOp(port=port_id),
    ):
        with pytest.raises(ValidationError, match="disconnect incident Edges"):
            apply_patch(
                layout,
                PatchIntent(ops=[op], actor="test", base_graph_version=before),
            )
        assert load_manifest(layout).graph_version == before
        assert port_exists(layout, port_id)
        assert edge_exists(layout, edge_id)

    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                UpdatePortOp(
                    port=port_id,
                    name="still_connected",
                    attrs={"label": "safe"},
                )
            ],
            actor="test",
            base_graph_version=before,
        ),
    )
    assert receipt.graph_version == before + 1
    assert load_port(layout, port_id).name == "still_connected"
    assert edge_exists(layout, edge_id)


def test_port_endpoints_and_edge_disconnect_follow_live_affordances(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path).layout
    model_id, _, _, connected_port_id, edge_id = _seed_ports(layout)
    client = TestClient(create_app(layout))

    connected_actions = {
        item["id"]: item
        for item in client.post(
            "/actions/resolve",
            json={"refs": [{"kind": "port", "id": connected_port_id}]},
        ).json()["affordances"]
    }
    assert connected_actions["port.update"]["enabled"]
    assert not connected_actions["port.delete"]["enabled"]
    assert connected_actions["port.delete"]["reason"] == (
        "disconnect incident Edges before deleting the Port"
    )

    safe_update = client.post(
        f"/port/{connected_port_id}/update",
        json={"name": "connected_output", "attrs": {"label": "out"}},
    )
    assert safe_update.status_code == 200, safe_update.text
    unsafe_update = client.post(
        f"/port/{connected_port_id}/update",
        json={"direction": "in"},
    )
    assert unsafe_update.status_code == 422
    assert unsafe_update.json()["detail"] == {
        "action": "port.update",
        "reason": "disconnect incident Edges before changing Port direction or type",
        "reason_code": "state_locked",
    }
    assert client.delete(f"/port/{connected_port_id}").status_code == 422
    assert edge_exists(layout, edge_id)

    disconnected = client.delete(f"/edge/{edge_id}")
    assert disconnected.status_code == 200, disconnected.text
    assert disconnected.json()["deleted"] == [edge_id]
    assert not edge_exists(layout, edge_id)

    disconnected_actions = {
        item["id"]: item
        for item in client.post(
            "/actions/resolve",
            json={"refs": [{"kind": "port", "id": connected_port_id}]},
        ).json()["affordances"]
    }
    assert disconnected_actions["port.delete"]["enabled"]

    changed = client.post(
        f"/port/{connected_port_id}/update",
        json={"direction": "in", "port_type": "scalar"},
    )
    assert changed.status_code == 200, changed.text
    removed = client.delete(f"/port/{connected_port_id}")
    assert removed.status_code == 200, removed.text
    assert removed.json()["deleted"] == [connected_port_id]

    created = client.post(
        f"/node/{model_id}/ports",
        json={
            "name": "new_input",
            "direction": "in",
            "port_type": "tensor",
            "attrs": {"confidence": "verified"},
        },
    )
    assert created.status_code == 200, created.text
    new_port_id = created.json()["port_id"]
    assert load_port(layout, new_port_id).node_id == model_id


def test_port_endpoints_reject_stale_invalid_and_unregistered_actions(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path).layout
    model_id, _, _, _, _ = _seed_ports(layout)
    client = TestClient(create_app(layout))
    before = load_manifest(layout).graph_version

    assert (
        client.post("/node/nod_missing/ports", json={"name": "x", "direction": "in"}).status_code
        == 404
    )
    assert client.post("/port/prt_missing/update", json={"name": "x"}).status_code == 404
    assert client.delete("/port/prt_missing").status_code == 404
    invalid_type = client.post(
        f"/node/{model_id}/ports",
        json={"name": "x", "direction": "in", "port_type": "unknown"},
    )
    assert invalid_type.status_code == 422
    invalid_direction = client.post(
        f"/node/{model_id}/ports",
        json={"name": "x", "direction": "sideways"},
    )
    assert invalid_direction.status_code == 422
    invalid_attrs = client.post(
        f"/node/{model_id}/ports",
        json={"name": "x", "direction": "in", "attrs": {"raw": True}},
    )
    assert invalid_attrs.status_code == 422
    assert load_manifest(layout).graph_version == before

    packages = tuple(
        replace(
            package,
            actions=tuple(action for action in package.actions if action.key != "port.create"),
        )
        if package.name == "core"
        else package
        for package in BUILTIN_PACKAGES
    )
    registry = Registry.build(version=2, packages=packages)
    denied = TestClient(create_app(layout, registry=registry)).post(
        f"/node/{model_id}/ports",
        json={"name": "blocked", "direction": "in", "port_type": "tensor"},
    )
    assert denied.status_code == 422
    assert denied.json()["detail"]["action"] == "port.create"
    assert denied.json()["detail"]["reason_code"] == "executor_unavailable"
    assert find_port(layout, model_id, "blocked") is None
    assert load_manifest(layout).graph_version == before


def test_contains_edge_never_exposes_or_executes_edge_delete(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    _, _, _, _, _ = _seed_ports(layout)
    contains = next(edge for edge in iter_edges(layout) if edge.type == "contains")
    client = TestClient(create_app(layout))

    actions = {
        item["id"]
        for item in client.post(
            "/actions/resolve",
            json={"refs": [{"kind": "edge", "id": contains.id}]},
        ).json()["affordances"]
    }
    assert "edge.delete" not in actions
    denied = client.delete(f"/edge/{contains.id}")
    assert denied.status_code == 422
    assert denied.json()["detail"]["reason_code"] == "missing_capability"
    assert edge_exists(layout, contains.id)
