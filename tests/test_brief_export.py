"""`brief export`: S3 — graph → analyst opening document, plan ingest's mirror.

Under test: determinism (same graph → byte-identical output), openness
criteria, evidence ids as citable currency, the escalate closure loop, and
the disagreement count sharing one computation with the server.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from simulanka.brief import export_brief, render_brief
from simulanka.disagreements import disagreement_list
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    CreatePortOp,
    PatchIntent,
    UpdateAttrsOp,
)
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.plan import PlanError, ingest_plan, resolve_escalate
from simulanka.runner import begin_run, end_run
from simulanka.storage.entity_store import iter_nodes, load_node


def _project(tmp_path: Path) -> ProjectLayout:
    return init_project(tmp_path).layout


def _write_plan(path: Path, block: dict[str, Any]) -> Path:
    path.write_text(
        "# 轮次分析\n\n自由推理散文，不进图。\n\n```simulanka-plan\n"
        + json.dumps(block) + "\n```\n",
        encoding="utf-8",
    )
    return path


def _ingest_round1(layout: ProjectLayout, tmp_path: Path) -> None:
    block = {
        "plan": {
            "questions": [{"lid": "q1", "body": "capacity or recency?"}],
            "hypotheses": [{"lid": "h1", "body": "recency dominates", "addresses": "q1"}],
            "experiments": [{
                "lid": "e1", "goal": "ablate recency window", "tests": "h1",
                "tasks": [{
                    "goal": "run the sweep", "allowed_outputs": ["**"],
                    "budget_time_seconds": 3600,
                }],
            }],
        },
    }
    ingest_plan(layout, _write_plan(tmp_path / "plan-round1.md", block))


def _block_of(markdown: str) -> dict[str, Any]:
    m = re.search(r"```simulanka-brief\n(.*?)```", markdown, re.DOTALL)
    assert m, markdown
    parsed = json.loads(m.group(1))
    assert isinstance(parsed, dict)
    return parsed


def _only_node(layout: ProjectLayout, node_type: str) -> str:
    [node] = [n for n in iter_nodes(layout) if n.type == node_type]
    return node.id


def test_brief_mirrors_graph_and_is_deterministic(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    _ingest_round1(layout, tmp_path)
    task_id = _only_node(layout, "task")

    begun = begin_run(layout, task=task_id, name="sweep-1")
    (tmp_path / "metrics.json").write_text(json.dumps({"acc": 0.91}), encoding="utf-8")
    ended = end_run(layout, run=begun.run_node_id)
    assert ended.evidence_node_id is not None

    markdown = render_brief(layout)
    block = _block_of(markdown)

    assert [q["body"] for q in block["open"]["questions"]] == ["capacity or recency?"]
    assert [h["body"] for h in block["open"]["hypotheses"]] == ["recency dominates"]
    assert block["open"]["claims"] == []

    [run_entry] = block["recent_runs"]
    assert run_entry["id"] == begun.run_node_id
    assert run_entry["task_goal"] == "run the sweep"
    assert run_entry["contract_check"] == "passed"
    # Evidence id is the citable currency for next round's supports edges.
    assert run_entry["evidence"] == [
        {"id": ended.evidence_node_id, "metrics": {"acc": 0.91}},
    ]

    [budget_row] = block["budget"]
    assert budget_row["budget_seconds"] == 3600.0
    assert budget_row["spent_seconds"] is not None and budget_row["spent_seconds"] >= 0

    assert block["escalations"] == []
    assert block["disagreements"] == 0

    # Same graph state → byte-identical output.
    assert render_brief(layout) == markdown
    assert run_doctor(layout).ok


def test_closed_atoms_and_done_experiments_excluded(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    _ingest_round1(layout, tmp_path)
    task_id = _only_node(layout, "task")
    begun = begin_run(layout, task=task_id)
    end_run(layout, run=begun.run_node_id)

    hyp_id = _only_node(layout, "hypothesis")
    exp_id = _only_node(layout, "experiment")
    apply_patch(layout, PatchIntent(
        ops=[
            UpdateAttrsOp(target=hyp_id, attrs={"verdict": "correct"}),
            UpdateAttrsOp(target=exp_id, attrs={"status": "done"}),
        ],
        actor="test",
        base_graph_version=layout.load_manifest().graph_version,
    ))

    block = _block_of(render_brief(layout))
    assert block["open"]["hypotheses"] == []
    assert block["recent_runs"] == []  # done experiment's runs are history
    assert block["budget"] == []


def test_escalate_closure_loop(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    result = ingest_plan(
        layout,
        _write_plan(
            tmp_path / "plan-stop.md",
            {"escalate": {"reason": "baseline numbers look impossible"}},
        ),
    )
    assert result.escalate_reason is not None

    [note] = [
        n for n in iter_nodes(layout)
        if n.type == "note" and n.attrs.get("kind") == "escalate"
    ]
    assert note.attrs["status"] == "open"

    markdown = render_brief(layout)
    assert "ESCALATE" in markdown
    block = _block_of(markdown)
    [entry] = block["escalations"]
    assert entry["id"] == note.id
    assert entry["body"] == "baseline numbers look impossible"

    resolved = resolve_escalate(layout, note.id, resolve_note="numbers re-checked, fine")
    assert resolved.attrs["status"] == "resolved"
    assert resolved.attrs["resolve_note"] == "numbers re-checked, fine"

    after = _block_of(render_brief(layout))
    assert after["escalations"] == []

    # Resolution is final; a second resolve is a user error.
    with pytest.raises(PlanError, match="already resolved"):
        resolve_escalate(layout, note.id)


def test_resolve_rejects_non_escalate_note(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    receipt = apply_patch(layout, PatchIntent(
        ops=[
            CreateNodeOp(type="directory", name="lab", ref="lab"),
            CreateNodeOp(type="note", name="plain", parent="@lab",
                         attrs={"body": "just a note"}),
        ],
        actor="test",
        base_graph_version=layout.load_manifest().graph_version,
    ))
    with pytest.raises(PlanError, match="not an escalate note"):
        resolve_escalate(layout, receipt.nodes[1])


def test_disagreement_count_shares_server_computation(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    receipt = apply_patch(layout, PatchIntent(
        ops=[
            CreateNodeOp(type="directory", name="models", ref="d"),
            CreateNodeOp(type="model", name="net", parent="@d", ref="m"),
        ],
        actor="test",
        base_graph_version=layout.load_manifest().graph_version,
    ))
    model_id = receipt.nodes[1]
    receipt2 = apply_patch(layout, PatchIntent(
        ops=[
            CreateNodeOp(type="module", name="a", parent=model_id),
            CreateNodeOp(type="module", name="b", parent=model_id),
        ],
        actor="test",
        base_graph_version=layout.load_manifest().graph_version,
    ))
    a_id, b_id = receipt2.nodes
    receipt3 = apply_patch(layout, PatchIntent(
        ops=[
            CreatePortOp(node=a_id, name="out", direction="out", port_type="tensor"),
            CreatePortOp(node=b_id, name="in", direction="in", port_type="tensor"),
        ],
        actor="test",
        base_graph_version=layout.load_manifest().graph_version,
    ))
    out_port, in_port = receipt3.ports
    apply_patch(layout, PatchIntent(
        ops=[CreateEdgeOp(
            type="data_flow", source=out_port, target=in_port,
            attrs={"source": "user", "verdict": "disputed"},
        )],
        actor="test",
        base_graph_version=layout.load_manifest().graph_version,
    ))

    block = _block_of(render_brief(layout))
    assert block["disagreements"] == 1
    assert block["disagreements"] == len(disagreement_list(layout))


def test_out_writes_registered_brief_file(tmp_path: Path) -> None:
    layout = _project(tmp_path)
    result = export_brief(layout, out="round2")
    assert result.relative_path == "research/brief-round2.md"
    on_disk = (tmp_path / "research" / "brief-round2.md").read_text(encoding="utf-8")
    assert on_disk == result.markdown
    assert result.file_node_id is not None
    node = load_node(layout, result.file_node_id)
    assert node.attrs["kind"] == "brief"
    assert node.created_by == "system"
    assert run_doctor(layout).ok


def test_cli_brief_and_note_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from simulanka.cli.app import app

    layout = _project(tmp_path)
    ingest_plan(
        layout,
        _write_plan(tmp_path / "plan-stop.md", {"escalate": {"reason": "stop"}}),
    )
    [note] = [
        n for n in iter_nodes(layout)
        if n.type == "note" and n.attrs.get("kind") == "escalate"
    ]
    monkeypatch.setenv("SIMULANKA_PROJECT", str(tmp_path))
    runner = CliRunner()

    exported = runner.invoke(app, ["brief", "export"])
    assert exported.exit_code == 0, exported.output
    assert "```simulanka-brief" in exported.output
    assert "ESCALATE" in exported.output

    resolved = runner.invoke(
        app, ["note", "resolve", note.id, "--note", "handled offline"],
    )
    assert resolved.exit_code == 0, resolved.output

    again = runner.invoke(app, ["note", "resolve", note.id])
    assert again.exit_code == 2

    quiet = runner.invoke(app, ["brief", "export"])
    assert "ESCALATE" not in quiet.output
