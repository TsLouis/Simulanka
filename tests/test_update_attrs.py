"""Tests for the update_attrs op."""

from __future__ import annotations

from pathlib import Path

import pytest

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    CreatePortOp,
    DeleteEdgeOp,
    PatchIntent,
    UpdateAttrsOp,
)
from simulanka.kernel.validator import ValidationError
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.storage.entity_store import load_edge, load_node


def _make_dir(layout: ProjectLayout) -> str:
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="root", attrs={"a": 1})],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    return receipt.nodes[0]


def test_merge_semantics_preserves_unspecified_keys(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    node_id = _make_dir(layout)

    apply_patch(
        layout,
        PatchIntent(
            ops=[UpdateAttrsOp(target=node_id, attrs={"b": 2})],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    node = load_node(layout, node_id)
    assert node.attrs == {"a": 1, "b": 2}

    # Overwrite existing key.
    apply_patch(
        layout,
        PatchIntent(
            ops=[UpdateAttrsOp(target=node_id, attrs={"a": 99})],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    node = load_node(layout, node_id)
    assert node.attrs == {"a": 99, "b": 2}


def test_update_returns_updated_id_in_receipt(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    node_id = _make_dir(layout)
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[UpdateAttrsOp(target=node_id, attrs={"status": "running"})],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    assert receipt.updated_nodes == [node_id]
    assert receipt.nodes == []  # nothing newly created


def test_update_bumps_graph_version_and_content_hash(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    node_id = _make_dir(layout)
    before = layout.load_manifest()

    apply_patch(
        layout,
        PatchIntent(
            ops=[UpdateAttrsOp(target=node_id, attrs={"k": "v"})],
            actor="test",
            base_graph_version=before.graph_version,
        ),
    )
    after = layout.load_manifest()
    assert after.graph_version == before.graph_version + 1
    assert after.content_hash != before.content_hash

    # Doctor stays green.
    assert run_doctor(layout).ok


def test_update_via_path_selector(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _make_dir(layout)
    apply_patch(
        layout,
        PatchIntent(
            ops=[UpdateAttrsOp(target="/root", attrs={"note": "via path"})],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    node = load_node(layout, _resolve(layout, "/root"))
    assert node.attrs["note"] == "via path"


def test_update_missing_node_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    with pytest.raises(ValidationError):
        apply_patch(
            layout,
            PatchIntent(
                ops=[UpdateAttrsOp(target="/nope", attrs={"x": 1})],
                actor="test",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )


def test_multiple_updates_in_same_patch_compose(tmp_path: Path) -> None:
    """Later update_attrs ops in the same patch see earlier ones merged in."""
    layout = init_project(tmp_path, with_scaffold=False).layout
    node_id = _make_dir(layout)
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                UpdateAttrsOp(target=node_id, attrs={"x": 1}),
                UpdateAttrsOp(target=node_id, attrs={"y": 2}),
                UpdateAttrsOp(target=node_id, attrs={"x": 99}),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    node = load_node(layout, node_id)
    assert node.attrs == {"a": 1, "x": 99, "y": 2}


def _resolve(layout: ProjectLayout, selector: str) -> str:
    from simulanka.kernel.resolver import resolve_node
    return resolve_node(layout, selector).id


# --- edge targets (§13.6: verdict/note write-back onto data_flow edges) ---


def _seed_data_flow_edge(layout: ProjectLayout) -> str:
    """conv1.out → bn1.in data_flow edge with seed attrs; returns its id."""
    for type_, name, parent in [
        ("directory", "models", None),
        ("model", "TinyNet", "/models"),
        ("module", "conv1", "/models/TinyNet"),
        ("module", "bn1", "/models/TinyNet"),
    ]:
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreateNodeOp(type=type_, name=name, parent=parent)],
                actor="test",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreatePortOp(node="/models/TinyNet/conv1", name="out", direction="out"),
                CreatePortOp(node="/models/TinyNet/bn1", name="in", direction="in"),
            ],
            actor="test",
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
                    attrs={"source": "user", "verdict": "unconfirmed"},
                ),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    return receipt.edges[0]


def test_update_edge_attrs_merges_and_reports(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    edge_id = _seed_data_flow_edge(layout)

    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[UpdateAttrsOp(
                target=edge_id,
                attrs={
                    "verdict": "wrong",
                    "verdict_by": "user",
                    "verdict_note": "skip 分支不经过 bn1",
                },
            )],
            actor="user",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    assert receipt.updated_edges == [edge_id]
    assert receipt.updated_nodes == []

    edge = load_edge(layout, edge_id)
    assert edge.attrs["source"] == "user"  # unspecified key preserved
    assert edge.attrs["verdict"] == "wrong"
    assert edge.attrs["verdict_by"] == "user"
    assert run_doctor(layout).ok


def test_update_missing_edge_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    with pytest.raises(ValidationError):
        apply_patch(
            layout,
            PatchIntent(
                ops=[UpdateAttrsOp(target="edg_doesnotexist", attrs={"x": 1})],
                actor="test",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )


def test_update_edge_deleted_earlier_in_patch_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    edge_id = _seed_data_flow_edge(layout)
    with pytest.raises(ValidationError):
        apply_patch(
            layout,
            PatchIntent(
                ops=[
                    DeleteEdgeOp(edge=edge_id),
                    UpdateAttrsOp(target=edge_id, attrs={"x": 1}),
                ],
                actor="test",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )


def test_multiple_edge_updates_in_same_patch_compose(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    edge_id = _seed_data_flow_edge(layout)
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                UpdateAttrsOp(target=edge_id, attrs={"verdict": "uncertain"}),
                UpdateAttrsOp(target=edge_id, attrs={"verdict_note": "n1"}),
                UpdateAttrsOp(target=edge_id, attrs={"verdict": "correct"}),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    edge = load_edge(layout, edge_id)
    assert edge.attrs["verdict"] == "correct"
    assert edge.attrs["verdict_note"] == "n1"
    assert edge.attrs["source"] == "user"
