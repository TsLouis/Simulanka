from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from simulanka.cli.app import app
from simulanka.kernel.apply import VersionConflict, apply_patch
from simulanka.kernel.events import iter_events
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.kernel.manifest import EMPTY_CONTENT_HASH
from simulanka.kernel.resolver import ResolveError, resolve_node
from simulanka.kernel.validator import ValidationError
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.storage.entity_store import iter_edges, iter_nodes, load_node


def _commit_root(layout: ProjectLayout, name: str = "models", node_type: str = "directory") -> str:
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type=node_type, name=name)],
            actor="user",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    return receipt.nodes[0]


def test_apply_create_root_node(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout

    intent = PatchIntent(
        ops=[CreateNodeOp(type="directory", name="models")],
        actor="user",
        base_graph_version=0,
    )
    receipt = apply_patch(layout, intent)

    assert receipt.graph_version == 1
    [node_id] = receipt.nodes
    assert receipt.edges == []  # 根节点不生成 contains
    node = load_node(layout, node_id)
    assert node.type == "directory"
    assert node.parent_id is None

    manifest = layout.load_manifest()
    assert manifest.graph_version == 1
    assert manifest.content_hash != EMPTY_CONTENT_HASH

    events = list(iter_events(layout))
    assert len(events) == 1
    assert events[0].ops[0]["entity_id"] == node_id


def test_apply_create_child_dual_writes_contains_edge(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    parent_id = _commit_root(layout)

    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="model", name="TinyNet", parent="/models")],
            actor="user",
            base_graph_version=1,
        ),
    )

    [child_id] = receipt.nodes
    [contains_id] = receipt.edges
    child = load_node(layout, child_id)
    assert child.parent_id == parent_id

    edges = list(iter_edges(layout))
    assert len(edges) == 1
    assert edges[0].id == contains_id
    assert edges[0].type == "contains"
    assert edges[0].source_id == parent_id
    assert edges[0].target_id == child_id


def test_version_conflict_is_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    with pytest.raises(VersionConflict):
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreateNodeOp(type="directory", name="models")],
                actor="user",
                base_graph_version=99,
            ),
        )


def test_missing_parent_fails_atomically(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    with pytest.raises(ValidationError):
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreateNodeOp(type="model", name="X", parent="/nope")],
                actor="user",
                base_graph_version=0,
            ),
        )
    assert layout.load_manifest().graph_version == 0
    assert list(iter_nodes(layout)) == []
    assert list(iter_edges(layout)) == []


def test_resolve_ambiguous_path_fails(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _commit_root(layout, name="dup")
    _commit_root(layout, name="dup")
    with pytest.raises(ResolveError):
        resolve_node(layout, "/dup")


def test_unknown_node_type_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    with pytest.raises(ValidationError) as ei:
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreateNodeOp(type="not_a_type", name="x")],
                actor="user",
                base_graph_version=0,
            ),
        )
    assert "Unknown node type" in str(ei.value)


def test_disallowed_parent_type_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    # model can't sit at root: allow_parents={"directory"}
    with pytest.raises(ValidationError) as ei:
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreateNodeOp(type="model", name="orphan")],
                actor="user",
                base_graph_version=0,
            ),
        )
    assert "cannot have parent" in str(ei.value)


def test_cli_node_create_and_inspect(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(project)]).exit_code == 0

    env = {"SIMULANKA_PROJECT": str(project)}
    created = runner.invoke(
        app,
        ["graph", "node", "create", "--type", "directory", "--name", "models"],
        env=env,
    )
    assert created.exit_code == 0, created.output
    assert "Created nod_" in created.output

    child = runner.invoke(
        app,
        [
            "graph", "node", "create",
            "--type", "model", "--name", "TinyNet",
            "--parent", "/models",
            "--attr", "layers=10",
            "--attr", "framework=pytorch",
        ],
        env=env,
    )
    assert child.exit_code == 0, child.output
    assert "contains edge: edg_" in child.output

    inspect = runner.invoke(app, ["graph", "node", "inspect", "/models/TinyNet"], env=env)
    assert inspect.exit_code == 0, inspect.output
    payload = json.loads(inspect.output.split("\n\n")[0])
    assert payload["name"] == "TinyNet"
    assert payload["attrs"] == {"layers": 10, "framework": "pytorch"}
