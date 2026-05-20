"""Tests for the rename_node op."""

from __future__ import annotations

from pathlib import Path

import pytest

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import (
    CreateNodeOp,
    PatchIntent,
    RenameNodeOp,
    UpdateAttrsOp,
)
from simulanka.kernel.resolver import ResolveError, resolve_node
from simulanka.kernel.validator import ValidationError
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.storage.entity_store import load_node


def _make_dir(layout: ProjectLayout, name: str, parent: str | None = None) -> str:
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name=name, parent=parent)],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    return receipt.nodes[0]


def test_rename_changes_name_and_keeps_attrs(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    node_id = _make_dir(layout, "old")
    apply_patch(
        layout,
        PatchIntent(
            ops=[UpdateAttrsOp(target=node_id, attrs={"k": "v"})],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )

    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[RenameNodeOp(target=node_id, new_name="new")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )

    assert receipt.updated_nodes == [node_id]
    node = load_node(layout, node_id)
    assert node.name == "new"
    assert node.attrs == {"k": "v"}

    # Old path no longer resolves; new path does.
    with pytest.raises(ResolveError):
        resolve_node(layout, "/old")
    assert resolve_node(layout, "/new").id == node_id


def test_rename_bumps_version_and_keeps_doctor_green(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    node_id = _make_dir(layout, "x")
    before = layout.load_manifest()
    apply_patch(
        layout,
        PatchIntent(
            ops=[RenameNodeOp(target=node_id, new_name="y")],
            actor="test",
            base_graph_version=before.graph_version,
        ),
    )
    after = layout.load_manifest()
    assert after.graph_version == before.graph_version + 1
    assert after.content_hash != before.content_hash
    assert run_doctor(layout).ok


def test_rename_rejects_empty_name(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    node_id = _make_dir(layout, "x")
    with pytest.raises(ValidationError):
        apply_patch(
            layout,
            PatchIntent(
                ops=[RenameNodeOp(target=node_id, new_name="")],
                actor="test",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )


def test_rename_rejects_sibling_collision(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    parent_id = _make_dir(layout, "parent")
    _make_dir(layout, "alpha", parent=parent_id)
    bravo_id = _make_dir(layout, "bravo", parent=parent_id)
    with pytest.raises(ValidationError, match="already named `alpha`"):
        apply_patch(
            layout,
            PatchIntent(
                ops=[RenameNodeOp(target=bravo_id, new_name="alpha")],
                actor="test",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )


def test_rename_allows_same_name_under_different_parent(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    p1 = _make_dir(layout, "p1")
    p2 = _make_dir(layout, "p2")
    _make_dir(layout, "x", parent=p1)
    y_under_p2 = _make_dir(layout, "y", parent=p2)
    apply_patch(
        layout,
        PatchIntent(
            ops=[RenameNodeOp(target=y_under_p2, new_name="x")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    assert load_node(layout, y_under_p2).name == "x"


def test_rename_missing_target_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    with pytest.raises(ValidationError):
        apply_patch(
            layout,
            PatchIntent(
                ops=[RenameNodeOp(target="/nope", new_name="anything")],
                actor="test",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )


def test_rename_combined_with_update_attrs_in_same_patch(tmp_path: Path) -> None:
    """A common pattern: rename a file/directory node and patch its fs_path."""
    layout = init_project(tmp_path, with_scaffold=False).layout
    node_id = _make_dir(layout, "old")
    apply_patch(
        layout,
        PatchIntent(
            ops=[UpdateAttrsOp(target=node_id, attrs={"fs_path": "baselines/old"})],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                RenameNodeOp(target=node_id, new_name="new"),
                UpdateAttrsOp(target=node_id, attrs={"fs_path": "baselines/new"}),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    node = load_node(layout, node_id)
    assert node.name == "new"
    assert node.attrs["fs_path"] == "baselines/new"


def test_rename_after_create_in_same_patch_sees_new_sibling(tmp_path: Path) -> None:
    """If the same patch creates `alpha` and tries to rename `bravo` to `alpha`,
    the collision must be caught."""
    layout = init_project(tmp_path, with_scaffold=False).layout
    parent_id = _make_dir(layout, "parent")
    bravo_id = _make_dir(layout, "bravo", parent=parent_id)
    with pytest.raises(ValidationError, match="already named `alpha`"):
        apply_patch(
            layout,
            PatchIntent(
                ops=[
                    CreateNodeOp(type="directory", name="alpha", parent=parent_id),
                    RenameNodeOp(target=bravo_id, new_name="alpha"),
                ],
                actor="test",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
