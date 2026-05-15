"""End-to-end tests for the run executor."""

from __future__ import annotations

from pathlib import Path

import pytest

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.runner import RunnerError, exec_run
from simulanka.storage.entity_store import iter_edges, iter_nodes, load_node


def _seed_experiment(layout: ProjectLayout) -> None:
    """Seed `/research/exp1` so we have a realistic parent for runs."""
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="research")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(
                    type="experiment",
                    name="exp1",
                    parent="/research",
                    attrs={"goal": "smoke", "status": "running"},
                ),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )


def test_successful_run_records_node_logs_and_edges(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_experiment(layout)

    result = exec_run(
        layout,
        command="printf 'hello %s' 'world'",
        parent="/research/exp1",
        name="r1",
    )
    assert result.status == "done"
    assert result.exit_code == 0
    assert (tmp_path / result.stdout_path).read_text() == "hello world"

    nodes = list(iter_nodes(layout))
    runs = [n for n in nodes if n.type == "run"]
    files = [n for n in nodes if n.type == "file"]
    assert len(runs) == 1
    assert runs[0].name == "r1"
    assert runs[0].attrs["agent"] == "shell"
    assert runs[0].attrs["exit_code"] == 0
    assert runs[0].attrs["status"] == "done"
    assert runs[0].attrs["stdout_path"] == result.stdout_path

    # Two log file nodes, both connected to the run via `produces`.
    log_files = {n.name: n for n in files if n.attrs.get("kind") == "run_log"}
    assert set(log_files) == {"r1.stdout.log", "r1.stderr.log"}

    produces = [e for e in iter_edges(layout) if e.type == "produces"]
    produces_targets = {e.target_id for e in produces if e.source_id == runs[0].id}
    assert produces_targets == {log_files["r1.stdout.log"].id, log_files["r1.stderr.log"].id}

    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_failing_run_is_marked_failed(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_experiment(layout)

    result = exec_run(
        layout, command="false", parent="/research/exp1", name="r_fail",
    )
    assert result.status == "failed"
    assert result.exit_code != 0
    run_node = load_node(layout, result.run_node_id)
    assert run_node.attrs["status"] == "failed"

    # Doctor still green even though the run failed — failed runs are recorded
    # but not treated as repository corruption.
    assert run_doctor(layout).ok


def test_run_under_directory_parent_also_works(tmp_path: Path) -> None:
    """Runs can be parented at a plain directory, not only at an experiment."""
    layout = init_project(tmp_path, with_scaffold=False).layout
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="adhoc")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    result = exec_run(layout, command="echo ok", parent="/adhoc", name="r_dir")
    assert result.status == "done"
    assert run_doctor(layout).ok


def test_run_with_invalid_parent_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="research")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(
                    type="model",
                    name="TinyNet",
                    parent="/research",
                    attrs={"class_name": "TinyNet"},
                ),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    with pytest.raises(RunnerError):
        exec_run(layout, command="true", parent="/research/TinyNet", name="r_bad")
