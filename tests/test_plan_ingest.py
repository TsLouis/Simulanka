"""§14.7 plan ingest: one fenced block → one atomic PatchIntent.

The distill/plan split is a parsing-regime split, not workflow: either
section may be absent; only an entirely empty block is rejected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.plan import PlanError, extract_plan_block, ingest_plan
from simulanka.schema.entities import Edge
from simulanka.storage.entity_store import iter_edges, iter_nodes, load_node


def _project(tmp_path: Path) -> ProjectLayout:
    return init_project(tmp_path).layout


def _seed_atoms(layout: ProjectLayout) -> dict[str, str]:
    """Prior-round entities a distill section can talk about."""
    receipt = apply_patch(layout, PatchIntent(
        ops=[
            CreateNodeOp(type="directory", name="lab", ref="lab"),
            CreateNodeOp(type="evidence", name="ev1", parent="@lab",
                         attrs={"body": "val acc 72.1 vs 70.3"}),
            CreateNodeOp(type="claim", name="cl1", parent="@lab",
                         attrs={"body": "memory bank helps", "status": "open"}),
            CreateNodeOp(type="hypothesis", name="hy1", parent="@lab",
                         attrs={"body": "longer memory helps more"}),
        ],
        actor="test",
        base_graph_version=layout.load_manifest().graph_version,
    ))
    lab, ev, cl, hy = receipt.nodes
    return {"lab": lab, "evidence": ev, "claim": cl, "hypothesis": hy}


def _write_plan(path: Path, block: dict[str, Any]) -> Path:
    path.write_text(
        "# 轮次分析\n\n自由推理散文，不进图。\n\n```simulanka-plan\n"
        + json.dumps(block) + "\n```\n",
        encoding="utf-8",
    )
    return path


def _full_block(ids: dict[str, str]) -> dict[str, Any]:
    return {
        "distill": {
            "new_claims": [
                {"lid": "c1", "body": "larger memory saturates past 8 frames"},
            ],
            "edges": [
                {"type": "supports", "source": ids["evidence"], "target": "c1",
                 "note": "72.1 > 70.3"},
                {"type": "contradicts", "source": ids["evidence"], "target": ids["claim"]},
            ],
            "claims": [{"id": ids["claim"], "status": "refuted", "note": "superseded by c1"}],
            "hypotheses": [{"id": ids["hypothesis"], "verdict": "uncertain"}],
        },
        "plan": {
            "questions": [{"lid": "q1", "body": "capacity or recency?"}],
            "hypotheses": [{"lid": "h1", "body": "recency dominates", "addresses": "q1"}],
            "experiments": [{
                "lid": "e1", "goal": "ablate recency window", "tests": "h1",
                "tasks": [
                    {"goal": "implement window sweep", "allowed_outputs": ["src/**"],
                     "acceptance": "pytest -q", "budget_time_seconds": 3600},
                    {"lid": "t9", "goal": "plot results"},
                ],
            }],
        },
        "escalate": None,
    }


def test_full_plan_lands_atomically(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    ids = _seed_atoms(layout)
    plan_file = _write_plan(tmp_path / "draft.md", _full_block(ids))

    result = ingest_plan(layout, plan_file)

    assert result.relative_path == "research/plan-draft.md"
    assert (tmp_path / "research/plan-draft.md").exists()
    assert result.escalate_reason is None

    nodes = {n.name: n for n in iter_nodes(layout)}
    plan_dir = nodes["plan-draft"]
    assert plan_dir.type == "directory"
    assert plan_dir.id == result.plan_dir_id

    for lid, typ in [("c1", "claim"), ("q1", "question"),
                     ("h1", "hypothesis"), ("e1", "experiment")]:
        atom = nodes[lid]
        assert atom.type == typ
        assert atom.parent_id == plan_dir.id
        assert atom.attrs["source"] == "analyst"
        assert atom.attrs["plan_file"] == "research/plan-draft.md"
        assert atom.attrs["plan_lid"] == lid
    assert nodes["e1"].attrs["status"] == "planned"
    assert nodes["c1"].attrs["status"] == "open"

    # Tasks: derived t1 + explicit t9, parent = experiment, §5.6 vocabulary.
    t1, t9 = nodes["t1"], nodes["t9"]
    assert t1.type == "task" and t1.parent_id == nodes["e1"].id
    assert t1.attrs["goal"] == "implement window sweep"
    assert t1.attrs["allowed_outputs"] == ["src/**"]
    assert t1.attrs["acceptance_command"] == "pytest -q"
    assert t1.attrs["budget_time_seconds"] == 3600
    assert t9.parent_id == nodes["e1"].id
    assert t9.attrs["acceptance_command"] is None

    by_type: dict[str, list[Edge]] = {}
    for edge in iter_edges(layout):
        by_type.setdefault(edge.type, []).append(edge)
    [sup] = by_type["supports"]
    assert sup.source_id == ids["evidence"] and sup.target_id == nodes["c1"].id
    assert sup.attrs["note"] == "72.1 > 70.3"
    assert sup.attrs["source"] == "analyst"
    [con] = by_type["contradicts"]
    assert con.source_id == ids["evidence"] and con.target_id == ids["claim"]
    [adr] = by_type["addresses"]
    assert adr.source_id == nodes["h1"].id and adr.target_id == nodes["q1"].id
    [tst] = by_type["tests"]
    assert tst.source_id == nodes["e1"].id and tst.target_id == nodes["h1"].id

    # Distill rewrites carry the reviewed_in stamp (§14.9 trust criterion).
    claim = load_node(layout, ids["claim"])
    assert claim.attrs["status"] == "refuted"
    assert claim.attrs["note"] == "superseded by c1"
    assert claim.attrs["reviewed_in"] == "research/plan-draft.md"
    hypo = load_node(layout, ids["hypothesis"])
    assert hypo.attrs["verdict"] == "uncertain"
    assert hypo.attrs["reviewed_in"] == "research/plan-draft.md"

    file_node = load_node(layout, result.file_node_id)
    assert file_node.attrs["kind"] == "plan"
    assert file_node.attrs["fs_path"] == "research/plan-draft.md"
    assert file_node.attrs["content_hash"].startswith("sha256:")


def test_rejects_zero_and_multiple_blocks(tmp_path: Path) -> None:
    with pytest.raises(PlanError, match="found 0"):
        extract_plan_block("# prose only, no block\n")
    two = ("```simulanka-plan\n{}\n```\nprose\n```simulanka-plan\n{}\n```\n")
    with pytest.raises(PlanError, match="found 2"):
        extract_plan_block(two)


def test_rejects_bad_json_and_unknown_keys(tmp_path: Path) -> None:
    with pytest.raises(PlanError, match="not valid JSON"):
        extract_plan_block("```simulanka-plan\n{not json}\n```\n")
    with pytest.raises(PlanError, match="schema validation"):
        extract_plan_block(
            "```simulanka-plan\n"
            + json.dumps({"plans": {"questions": []}})  # typo'd top-level key
            + "\n```\n"
        )


def test_rejects_empty_block(tmp_path: Path) -> None:
    with pytest.raises(PlanError, match="empty"):
        extract_plan_block("```simulanka-plan\n{}\n```\n")


def test_verdict_vocabulary_enforced(tmp_path: Path) -> None:
    block = {"distill": {"hypotheses": [{"id": "x", "verdict": "supported"}]}}
    with pytest.raises(PlanError, match="schema validation"):
        extract_plan_block("```simulanka-plan\n" + json.dumps(block) + "\n```\n")


def test_rejects_duplicate_lids(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    block = {"plan": {
        "questions": [{"lid": "q1", "body": "a?"}],
        "hypotheses": [{"lid": "q1", "body": "b", "addresses": "q1"}],
    }}
    plan_file = _write_plan(tmp_path / "dup.md", block)
    with pytest.raises(PlanError, match="more than once"):
        ingest_plan(layout, plan_file)


def test_distill_edge_target_must_be_new_claim_lid(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    ids = _seed_atoms(layout)
    block = {
        "distill": {"edges": [
            {"type": "supports", "source": ids["evidence"], "target": "q1"},
        ]},
        "plan": {"questions": [{"lid": "q1", "body": "a?"}]},
    }
    plan_file = _write_plan(tmp_path / "wrongkind.md", block)
    with pytest.raises(PlanError, match="not a new_claims lid"):
        ingest_plan(layout, plan_file)


def test_distill_update_requires_matching_type(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    ids = _seed_atoms(layout)
    block = {"distill": {"claims": [{"id": ids["hypothesis"], "status": "refuted"}]}}
    plan_file = _write_plan(tmp_path / "wrongtype.md", block)
    with pytest.raises(PlanError, match="want claim"):
        ingest_plan(layout, plan_file)


def test_unknown_reference_rejected_before_landing(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    _seed_atoms(layout)
    block = {"distill": {"claims": [{"id": "nod_00000000000000000000000000", "status": "open"}]}}
    plan_file = _write_plan(tmp_path / "ghostref.md", block)
    version_before = layout.load_manifest().graph_version
    with pytest.raises(PlanError):
        ingest_plan(layout, plan_file)
    assert layout.load_manifest().graph_version == version_before
    assert not (tmp_path / "research/plan-ghostref.md").exists()


def test_kernel_rejection_is_atomic(tmp_path: Path) -> None:
    """A failure only the kernel can see (reserved name prefix) leaves no trace."""
    layout = _project(tmp_path)
    # `nod_1` passes the lid charset but is a §2 reserved node name.
    block = {"plan": {"questions": [{"lid": "nod_1", "body": "reserved"}]}}
    plan_file = _write_plan(tmp_path / "clash.md", block)
    version_before = layout.load_manifest().graph_version
    with pytest.raises(PlanError, match="kernel"):
        ingest_plan(layout, plan_file)
    assert layout.load_manifest().graph_version == version_before
    assert not (tmp_path / "research/plan-clash.md").exists()
    assert all(n.name != "plan-clash" for n in iter_nodes(layout))


def test_escalate_is_reserved_lid(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    block = {
        "plan": {"questions": [{"lid": "escalate", "body": "collides with note name"}]},
        "escalate": {"reason": "stop"},
    }
    plan_file = _write_plan(tmp_path / "reserved.md", block)
    with pytest.raises(PlanError, match="reserved lid"):
        ingest_plan(layout, plan_file)


def test_duplicate_ingest_rejected(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    block = {"plan": {"questions": [{"lid": "q1", "body": "a?"}]}}
    plan_file = _write_plan(tmp_path / "once.md", block)
    ingest_plan(layout, plan_file)
    with pytest.raises(PlanError, match="already ingested"):
        ingest_plan(layout, plan_file)


def test_in_place_ingest_under_research(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    block = {"plan": {"questions": [{"lid": "q1", "body": "a?"}]}}
    plan_file = _write_plan(tmp_path / "research" / "plan-r2.md", block)

    result = ingest_plan(layout, plan_file)

    assert result.relative_path == "research/plan-r2.md"
    file_node = load_node(layout, result.file_node_id)
    assert file_node.attrs["fs_path"] == "research/plan-r2.md"


def test_in_place_requires_policy_name(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    block = {"plan": {"questions": [{"lid": "q1", "body": "a?"}]}}
    plan_file = _write_plan(tmp_path / "research" / "analysis.md", block)
    with pytest.raises(PlanError, match="not named `plan-"):
        ingest_plan(layout, plan_file)


def test_escalate_only_plan(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    block = {"escalate": {"reason": "baselines disagree; need human call"}}
    plan_file = _write_plan(tmp_path / "stop.md", block)

    result = ingest_plan(layout, plan_file)

    assert result.escalate_reason == "baselines disagree; need human call"
    notes = [n for n in iter_nodes(layout) if n.type == "note"]
    [note] = notes
    assert note.name == "escalate"
    assert note.attrs["kind"] == "escalate"
    assert note.attrs["body"] == "baselines disagree; need human call"
    assert note.parent_id == result.plan_dir_id


def test_graph_selector_references_resolve(tmp_path: Path) -> None:
    """addresses/tests may point at prior-round entities by graph id."""
    layout = _project(tmp_path)
    ids = _seed_atoms(layout)
    block = {"plan": {"experiments": [
        {"lid": "e1", "goal": "retest", "tests": ids["hypothesis"]},
    ]}}
    plan_file = _write_plan(tmp_path / "retest.md", block)

    ingest_plan(layout, plan_file)

    [tst] = [e for e in iter_edges(layout) if e.type == "tests"]
    assert tst.target_id == ids["hypothesis"]
