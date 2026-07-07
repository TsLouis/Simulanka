"""§3 intent-local @ref handles + reserved-name validation.

The @ref primitive exists so a multi-entity narrative (§14.7 plan ingest)
lands in ONE PatchIntent: the disk resolver cannot see pending nodes, so
"create a node and wire an edge to it" was impossible atomically before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    PatchIntent,
    RenameNodeOp,
)
from simulanka.kernel.validator import ValidationError
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.storage.entity_store import iter_edges, iter_nodes, load_node


def _intent(layout: ProjectLayout, *ops: CreateNodeOp | CreateEdgeOp | RenameNodeOp) -> PatchIntent:
    return PatchIntent(
        ops=list(ops),
        actor="analyst",
        base_graph_version=layout.load_manifest().graph_version,
    )


def test_plan_shaped_intent_lands_atomically(tmp_path: Path) -> None:
    """The §14.7 dry-run shape: dir → atoms inside it → semantic edges, one intent."""
    layout = init_project(tmp_path, with_scaffold=False).layout

    receipt = apply_patch(layout, _intent(
        layout,
        CreateNodeOp(type="directory", name="research", ref="root"),
        CreateNodeOp(type="directory", name="plan-r1", parent="@root", ref="plan"),
        CreateNodeOp(type="question", name="q1", parent="@plan", ref="q1",
                     attrs={"body": "?"}),
        CreateNodeOp(type="hypothesis", name="h1", parent="@plan", ref="h1",
                     attrs={"body": "!"}),
        CreateEdgeOp(type="addresses", source="@h1", target="@q1"),
    ))

    assert len(receipt.nodes) == 4
    nodes = {n.name: n for n in iter_nodes(layout)}
    assert nodes["q1"].parent_id == nodes["plan-r1"].id
    assert nodes["h1"].parent_id == nodes["plan-r1"].id
    semantic = [e for e in iter_edges(layout) if e.type == "addresses"]
    assert len(semantic) == 1
    assert semantic[0].source_id == nodes["h1"].id
    assert semantic[0].target_id == nodes["q1"].id
    # Handles are intent-local: nothing about them persists.
    assert "ref" not in load_node(layout, nodes["q1"].id).model_dump()["attrs"]


def test_unknown_ref_rejects_whole_intent(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout

    with pytest.raises(ValidationError, match="unknown ref `@nope`"):
        apply_patch(layout, _intent(
            layout,
            CreateNodeOp(type="directory", name="research"),
            CreateNodeOp(type="question", name="q1", parent="@nope"),
        ))
    # Atomicity: the valid first op must not have landed either.
    assert list(iter_nodes(layout)) == []


def test_ref_only_visible_to_later_ops(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout

    with pytest.raises(ValidationError, match="unknown ref `@late`"):
        apply_patch(layout, _intent(
            layout,
            CreateNodeOp(type="directory", name="a", parent="@late"),
            CreateNodeOp(type="directory", name="b", ref="late"),
        ))


def test_duplicate_ref_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout

    with pytest.raises(ValidationError, match="ref `dup` already declared"):
        apply_patch(layout, _intent(
            layout,
            CreateNodeOp(type="directory", name="a", ref="dup"),
            CreateNodeOp(type="directory", name="b", ref="dup"),
        ))


def test_edge_to_ref_endpoint_gets_type_validated(tmp_path: Path) -> None:
    """@ref resolution must not bypass §5.1 endpoint-type validation."""
    layout = init_project(tmp_path, with_scaffold=False).layout

    with pytest.raises(ValidationError, match="rejects source node type `experiment`"):
        apply_patch(layout, _intent(
            layout,
            CreateNodeOp(type="directory", name="research", ref="root"),
            CreateNodeOp(type="question", name="q1", parent="@root", ref="q1"),
            CreateNodeOp(type="experiment", name="e1", parent="@root", ref="e1"),
            CreateEdgeOp(type="addresses", source="@e1", target="@q1"),
        ))


def test_reserved_prefixes_rejected_on_create(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout

    for bad in ("nod_x", "edg_x", "prt_x", "@x"):
        with pytest.raises(ValidationError, match="reserved"):
            apply_patch(layout, _intent(
                layout, CreateNodeOp(type="directory", name=bad),
            ))
    assert list(iter_nodes(layout)) == []


def test_reserved_prefixes_rejected_on_rename(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    apply_patch(layout, _intent(
        layout, CreateNodeOp(type="directory", name="fine"),
    ))

    with pytest.raises(ValidationError, match="reserved id prefix"):
        apply_patch(layout, _intent(
            layout, RenameNodeOp(target="/fine", new_name="edg_sneaky"),
        ))
