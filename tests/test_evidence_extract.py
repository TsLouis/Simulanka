"""`evidence extract`: S2 — metrics file → evidence node, one deterministic path.

Honesty rules under test: whole-file rejection on any non-scalar (recorded as
`metrics_error`), idempotent re-extraction, history never overwritten.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from simulanka.contract import TaskContract, task_node_attrs
from simulanka.evidence import EvidenceError, MetricsError, extract_evidence
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.runner import begin_run, end_run
from simulanka.storage.entity_store import iter_edges, iter_nodes, load_node


def _seed_run(layout: ProjectLayout, tmp_path: Path) -> str:
    """Bracket run under /research/exp1; returns the run node id (still running)."""
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(type="directory", name="research", ref="dir"),
                CreateNodeOp(type="experiment", name="exp1", parent="@dir", ref="exp"),
                CreateNodeOp(
                    type="task",
                    name="measure",
                    parent="@exp",
                    attrs=task_node_attrs(TaskContract(goal="produce metrics")),
                ),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    task_id = receipt.nodes[2]
    return begin_run(layout, task=task_id).run_node_id


def _write_metrics(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_extract_creates_evidence_node(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)
    _write_metrics(tmp_path, {"acc": 0.93, "loss": 0.12, "epochs": 10, "converged": True})

    result = extract_evidence(layout, run=run_id)
    assert result.created is True
    assert result.metrics == {"acc": 0.93, "loss": 0.12, "epochs": 10, "converged": True}

    node = load_node(layout, result.evidence_node_id)
    assert node.type == "evidence"
    assert node.parent_id == run_id
    assert node.attrs["source"] == "machine"
    assert node.attrs["metrics_path"] == "metrics.json"
    assert node.attrs["body"] == "acc=0.93, converged=True, epochs=10, loss=0.12"

    produces = [
        e for e in iter_edges(layout)
        if e.type == "produces" and e.target_id == result.evidence_node_id
    ]
    assert len(produces) == 1
    assert produces[0].source_id == run_id
    # No semantic edges — the analyst judges, not the extractor.
    assert not [
        e for e in iter_edges(layout)
        if e.source_id == result.evidence_node_id
    ]
    assert run_doctor(layout).ok


def test_extract_is_idempotent_on_same_content(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)
    _write_metrics(tmp_path, {"acc": 0.9})

    first = extract_evidence(layout, run=run_id)
    second = extract_evidence(layout, run=run_id)
    assert second.created is False
    assert second.evidence_node_id == first.evidence_node_id
    assert len([n for n in iter_nodes(layout) if n.type == "evidence"]) == 1


def test_changed_metrics_mint_new_evidence(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)
    _write_metrics(tmp_path, {"acc": 0.9})
    first = extract_evidence(layout, run=run_id)

    _write_metrics(tmp_path, {"acc": 0.95})
    second = extract_evidence(layout, run=run_id)
    assert second.created is True
    assert second.evidence_node_id != first.evidence_node_id
    # History is not rewritten — both evidence nodes exist.
    evidences = [n for n in iter_nodes(layout) if n.type == "evidence"]
    assert len(evidences) == 2
    assert load_node(layout, first.evidence_node_id).attrs["metrics"] == {"acc": 0.9}


@pytest.mark.parametrize(
    ("payload", "reason_fragment"),
    [
        ({"nested": {"a": 1}}, "dict"),
        ({"listy": [1, 2]}, "list"),
        ({"nullish": None}, "NoneType"),
        ([1, 2, 3], "top level"),
        ({}, "empty"),
    ],
)
def test_invalid_metrics_rejected_whole_file(
    tmp_path: Path, payload: object, reason_fragment: str,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)
    _write_metrics(tmp_path, payload)

    with pytest.raises(MetricsError, match=reason_fragment):
        extract_evidence(layout, run=run_id)
    # No partial extraction, rejection recorded on the run node.
    assert not [n for n in iter_nodes(layout) if n.type == "evidence"]
    run_node = load_node(layout, run_id)
    assert isinstance(run_node.attrs["metrics_error"], str)


def test_metrics_error_cleared_on_later_success(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)
    _write_metrics(tmp_path, {"bad": None})
    with pytest.raises(MetricsError):
        extract_evidence(layout, run=run_id)

    _write_metrics(tmp_path, {"acc": 0.9})
    extract_evidence(layout, run=run_id)
    assert load_node(layout, run_id).attrs["metrics_error"] is None


def test_missing_file_is_usage_error_not_recorded(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)

    with pytest.raises(EvidenceError, match="does not exist"):
        extract_evidence(layout, run=run_id)
    with pytest.raises(EvidenceError, match="not found"):
        extract_evidence(layout, run=run_id, metrics=Path("elsewhere.json"))
    # A file that never existed measured nothing — no metrics_error stamp.
    assert "metrics_error" not in load_node(layout, run_id).attrs


def test_run_end_extracts_conventional_metrics(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)
    _write_metrics(tmp_path, {"acc": 0.93})

    ended = end_run(layout, run=run_id)
    assert ended.metrics_error is None
    assert ended.evidence_node_id is not None
    assert ended.evidence_created is True
    node = load_node(layout, ended.evidence_node_id)
    assert node.attrs["metrics"] == {"acc": 0.93}
    assert run_doctor(layout).ok


def test_run_end_without_metrics_is_silent(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)
    ended = end_run(layout, run=run_id)
    assert ended.evidence_node_id is None
    assert ended.metrics_error is None


def test_run_end_reports_invalid_metrics_but_still_seals(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)
    _write_metrics(tmp_path, {"nested": {"a": 1}})

    ended = end_run(layout, run=run_id)
    assert ended.status == "done"  # the seal is not blocked
    assert ended.evidence_node_id is None
    assert ended.metrics_error is not None
    run_node = load_node(layout, run_id)
    assert run_node.attrs["status"] == "done"
    assert isinstance(run_node.attrs["metrics_error"], str)


def test_run_end_with_explicit_metrics_path(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)
    other = tmp_path / "results" / "final.json"
    other.parent.mkdir()
    other.write_text(json.dumps({"f1": 0.7}), encoding="utf-8")

    ended = end_run(layout, run=run_id, metrics=other)
    assert ended.evidence_node_id is not None
    node = load_node(layout, ended.evidence_node_id)
    assert node.attrs["metrics"] == {"f1": 0.7}
    assert node.attrs["metrics_path"] == "results/final.json"


def test_cli_extract_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from simulanka.cli.app import app

    layout = init_project(tmp_path, with_scaffold=False).layout
    run_id = _seed_run(layout, tmp_path)
    monkeypatch.setenv("SIMULANKA_PROJECT", str(tmp_path))
    runner = CliRunner()

    # Missing file → usage error (2).
    missing = runner.invoke(app, ["evidence", "extract", run_id])
    assert missing.exit_code == 2

    _write_metrics(tmp_path, {"acc": 0.9})
    ok = runner.invoke(app, ["evidence", "extract", run_id])
    assert ok.exit_code == 0, ok.output
    assert "Evidence recorded" in ok.output

    again = runner.invoke(app, ["evidence", "extract", run_id])
    assert again.exit_code == 0
    assert "no-op" in again.output

    _write_metrics(tmp_path, {"bad": [1]})
    rejected = runner.invoke(app, ["evidence", "extract", run_id])
    assert rejected.exit_code == 1
