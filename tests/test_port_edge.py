from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from simulanka.cli.app import app
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    CreatePortOp,
    DeleteEdgeOp,
    PatchIntent,
)
from simulanka.kernel.resolver import resolve_port
from simulanka.kernel.validator import ValidationError
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.registry.types import PortDirection
from simulanka.storage.entity_store import (
    edge_exists,
    find_port,
    iter_edges,
    list_ports_of,
    load_edge,
)


def _seed_two_modules(layout: ProjectLayout) -> None:
    """Creates /models/TinyNet/conv1 and /models/TinyNet/bn1."""
    ops = [
        ("directory", "models", None),
        ("model", "TinyNet", "/models"),
        ("module", "conv1", "/models/TinyNet"),
        ("module", "bn1", "/models/TinyNet"),
    ]
    for type_, name, parent in ops:
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreateNodeOp(type=type_, name=name, parent=parent)],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )


def test_create_port_and_inspect(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_two_modules(layout)

    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreatePortOp(
                    node="/models/TinyNet/conv1",
                    name="out",
                    direction="out",
                    port_type="tensor",
                )
            ],
            actor="user",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    [port_id] = receipt.ports

    port = resolve_port(layout, "/models/TinyNet/conv1.out")
    assert port.id == port_id
    assert find_port(layout, port.node_id, "out") is not None
    assert [p.id for p in list_ports_of(layout, port.node_id)] == [port_id]


def test_connect_data_flow_via_selectors(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_two_modules(layout)

    endpoints: list[tuple[str, PortDirection]] = [
        ("/models/TinyNet/conv1", "out"),
        ("/models/TinyNet/bn1", "in"),
    ]
    for selector, direction in endpoints:
        apply_patch(
            layout,
            PatchIntent(
                ops=[
                    CreatePortOp(
                        node=selector,
                        name=direction,
                        direction=direction,
                        port_type="tensor",
                    )
                ],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )

    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateEdgeOp(
                    type="data_flow",
                    source="/models/TinyNet/conv1.out",
                    target="/models/TinyNet/bn1.in",
                )
            ],
            actor="user",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    [edge_id] = receipt.edges
    edge = load_edge(layout, edge_id)
    assert edge.type == "data_flow"
    assert edge.source_port_id is not None
    assert edge.target_port_id is not None


def test_data_flow_requires_ports(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_two_modules(layout)
    with pytest.raises(ValidationError) as ei:
        apply_patch(
            layout,
            PatchIntent(
                ops=[
                    CreateEdgeOp(
                        type="data_flow",
                        source="/models/TinyNet/conv1",
                        target="/models/TinyNet/bn1",
                    )
                ],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    assert "requires explicit source and target ports" in str(ei.value)


def test_data_flow_rejects_wrong_direction(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_two_modules(layout)
    # 都建成 "out" 方向；connect 时 target 端就不合规
    for selector in ["/models/TinyNet/conv1", "/models/TinyNet/bn1"]:
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreatePortOp(node=selector, name="p", direction="out", port_type="any")],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    with pytest.raises(ValidationError) as ei:
        apply_patch(
            layout,
            PatchIntent(
                ops=[
                    CreateEdgeOp(
                        type="data_flow",
                        source="/models/TinyNet/conv1.p",
                        target="/models/TinyNet/bn1.p",
                    )
                ],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    msg = str(ei.value)
    assert "direction" in msg and "expected `in`" in msg


def test_port_name_collision_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_two_modules(layout)
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreatePortOp(
                    node="/models/TinyNet/conv1",
                    name="out",
                    direction="out",
                    port_type="any",
                )
            ],
            actor="user",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    with pytest.raises(ValidationError) as ei:
        apply_patch(
            layout,
            PatchIntent(
                ops=[
                CreatePortOp(
                    node="/models/TinyNet/conv1",
                    name="out",
                    direction="out",
                    port_type="any",
                )
            ],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    assert "already exists" in str(ei.value)


def test_contains_edge_rejects_non_container_source(tmp_path: Path) -> None:
    """`contains.source` is restricted; non-container types shouldn't get auto-contains."""
    # Build /models, then try to put a directory under TinyNet (model).
    # `directory.allow_parents = {directory, None}`, so this should fail at node-level
    # *before* we even reach the contains validation. We assert one of the two messages.
    layout = init_project(tmp_path, with_scaffold=False).layout
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="models")],
            actor="user",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="model", name="TinyNet", parent="/models")],
            actor="user",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    with pytest.raises(ValidationError) as ei:
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreateNodeOp(type="directory", name="oops", parent="/models/TinyNet")],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    assert "cannot have parent" in str(ei.value)


def test_cli_full_acceptance_flow(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "proj"
    runner.invoke(app, ["init", str(project)])
    env = {"SIMULANKA_PROJECT": str(project)}

    def run(*args: str) -> None:
        result = runner.invoke(app, list(args), env=env)
        assert result.exit_code == 0, result.output

    run("graph", "node", "create", "--type", "directory", "--name", "models")
    run("graph", "node", "create", "--type", "model", "--name", "TinyNet", "--parent", "/models")
    run("graph", "node", "create",
        "--type", "module", "--name", "conv1", "--parent", "/models/TinyNet")
    run("graph", "node", "create",
        "--type", "module", "--name", "bn1", "--parent", "/models/TinyNet")
    run("graph", "port", "create", "/models/TinyNet/conv1",
        "--name", "out", "--direction", "out", "--type", "tensor")
    run("graph", "port", "create", "/models/TinyNet/bn1",
        "--name", "in", "--direction", "in", "--type", "tensor")
    run("graph", "connect",
        "/models/TinyNet/conv1.out", "/models/TinyNet/bn1.in", "--type", "data_flow")

    inspect = runner.invoke(
        app, ["graph", "node", "inspect", "/models/TinyNet/conv1"], env=env
    )
    assert inspect.exit_code == 0
    assert "ports:" in inspect.output
    assert "out" in inspect.output

    # 校验事件 + edges 数量：4 nodes (1 root + 3 children) + 3 contains + 1 data_flow
    edges = list(iter_edges(_layout(project)))
    assert sum(1 for e in edges if e.type == "contains") == 3
    assert sum(1 for e in edges if e.type == "data_flow") == 1


def _seed_data_flow_edge(layout: ProjectLayout) -> str:
    """conv1.out → bn1.in data_flow edge under a seeded TinyNet; returns its id."""
    _seed_two_modules(layout)
    endpoints: list[tuple[str, PortDirection]] = [
        ("/models/TinyNet/conv1", "out"),
        ("/models/TinyNet/bn1", "in"),
    ]
    for selector, direction in endpoints:
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreatePortOp(
                    node=selector, name=direction, direction=direction, port_type="tensor",
                )],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[CreateEdgeOp(
                type="data_flow",
                source="/models/TinyNet/conv1.out",
                target="/models/TinyNet/bn1.in",
            )],
            actor="user",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    return receipt.edges[0]


def test_delete_data_flow_edge(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    edge_id = _seed_data_flow_edge(layout)
    assert edge_exists(layout, edge_id)

    before = layout.load_manifest().graph_version
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[DeleteEdgeOp(edge=edge_id)],
            actor="user",
            base_graph_version=before,
        ),
    )
    assert receipt.deleted_edges == [edge_id]
    assert receipt.graph_version == before + 1
    assert not edge_exists(layout, edge_id)
    assert all(e.id != edge_id for e in iter_edges(layout))
    # The endpoint nodes and ports are untouched; graph stays healthy.
    assert run_doctor(layout).ok


def test_delete_edge_refuses_contains(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_two_modules(layout)
    contains = next(e for e in iter_edges(layout) if e.type == "contains")
    with pytest.raises(ValidationError) as ei:
        apply_patch(
            layout,
            PatchIntent(
                ops=[DeleteEdgeOp(edge=contains.id)],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    assert "contains" in str(ei.value)
    assert edge_exists(layout, contains.id)  # untouched


def test_delete_edge_missing_id_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_two_modules(layout)
    with pytest.raises(ValidationError) as ei:
        apply_patch(
            layout,
            PatchIntent(
                ops=[DeleteEdgeOp(edge="edg_doesnotexist")],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    assert "not found" in str(ei.value)


def _layout(project: Path) -> ProjectLayout:
    return ProjectLayout(project.resolve())
