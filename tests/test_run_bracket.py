"""Execution bracket (`run begin` / `run end`): S1 of the static build-out.

The system measures at both ends — snapshot + contract mirror at begin,
diff + acceptance + seal at end — and stays out of the middle.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from simulanka.contract import AcceptanceSpec, BudgetSpec, TaskContract, task_node_attrs
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import CreateNodeOp, PatchIntent, UpdateAttrsOp
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.runner import RunnerError, begin_run, end_run, exec_run
from simulanka.storage.entity_store import iter_edges, load_node


def _seed(layout: ProjectLayout) -> str:
    """Create /research + an experiment under it; return the experiment id."""
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(type="directory", name="research", ref="dir"),
                CreateNodeOp(type="experiment", name="exp1", parent="@dir"),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    return receipt.nodes[1]


def _create_task(
    layout: ProjectLayout, *, parent: str, name: str, contract: TaskContract,
) -> str:
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(
                    type="task",
                    name=name,
                    parent=parent,
                    attrs=task_node_attrs(contract),
                ),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    [task_id] = receipt.nodes
    return task_id


def test_begin_end_happy_path(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    exp_id = _seed(layout)
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "existing.py").write_text("old\n", encoding="utf-8")

    task_id = _create_task(
        layout,
        parent=exp_id,
        name="touch-src",
        contract=TaskContract(
            goal="modify workspace",
            allowed_outputs=["workspace/**"],
            budget=BudgetSpec(time_seconds=30),
            acceptance=AcceptanceSpec(command="test -f workspace/new.py"),
        ),
    )

    begun = begin_run(layout, task=task_id, name="attempt1")
    node = load_node(layout, begun.run_node_id)
    assert node.attrs["status"] == "running"
    assert node.attrs["bracket"] is True
    assert node.attrs["contract"]["task_node_id"] == task_id
    assert node.attrs["contract"]["allowed_outputs"] == ["workspace/**"]
    assert node.attrs["started_at"] is not None
    assert node.attrs["ended_at"] is None
    # tmp_path is not a git repo — no pretend metadata.
    assert "git_head" not in node.attrs

    fulfills = [
        e for e in iter_edges(layout)
        if e.type == "fulfills" and e.source_id == begun.run_node_id
    ]
    assert len(fulfills) == 1
    assert fulfills[0].target_id == task_id

    snapshot = json.loads((begun.run_dir / "snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["workdir"] == str(tmp_path)
    assert any(k.endswith("existing.py") for k in snapshot["files"])
    contract_snap = json.loads(
        (begun.run_dir / "contract.json").read_text(encoding="utf-8"),
    )
    assert contract_snap["task_node_id"] == task_id

    # The human works in their own terminal.
    (tmp_path / "workspace" / "new.py").write_text("created\n", encoding="utf-8")
    (tmp_path / "workspace" / "existing.py").write_text("bumped\n", encoding="utf-8")

    ended = end_run(layout, run=begun.run_node_id)
    assert ended.status == "done"
    assert ended.files_added == ["workspace/new.py"]
    assert ended.files_modified == ["workspace/existing.py"]
    assert ended.files_deleted == []
    assert ended.contract_check is not None
    assert ended.contract_check.status == "passed"
    assert ended.contract_check.acceptance_exit_code == 0
    assert ended.duration_seconds >= 0

    node = load_node(layout, begun.run_node_id)
    assert node.attrs["status"] == "done"
    assert node.attrs["ended_at"] is not None
    assert node.attrs["contract_check"]["status"] == "passed"
    changes = json.loads(
        (layout.root / ended.changes_path).read_text(encoding="utf-8"),
    )
    assert changes["added"] == ["workspace/new.py"]
    assert (begun.run_dir / "acceptance.log").exists()

    assert run_doctor(layout).ok


def test_begin_defaults_parent_to_task_parent(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    exp_id = _seed(layout)
    task_id = _create_task(
        layout, parent=exp_id, name="t", contract=TaskContract(goal="x"),
    )
    begun = begin_run(layout, task=task_id)
    node = load_node(layout, begun.run_node_id)
    assert node.parent_id == exp_id
    # Default name is derived from the run handle.
    assert node.name.startswith("run-")


def test_end_flags_out_of_scope(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    exp_id = _seed(layout)
    task_id = _create_task(
        layout,
        parent=exp_id,
        name="strict",
        contract=TaskContract(goal="x", allowed_outputs=["workspace/**"]),
    )
    begun = begin_run(layout, task=task_id)
    (tmp_path / "leaked.txt").write_text("oops\n", encoding="utf-8")

    ended = end_run(layout, run=begun.run_node_id)
    assert ended.contract_check is not None
    assert ended.contract_check.status == "out_of_scope"
    assert "leaked.txt" in ended.contract_check.out_of_scope_files
    node = load_node(layout, begun.run_node_id)
    assert node.attrs["contract_check"]["status"] == "out_of_scope"


def test_end_twice_rejected(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    exp_id = _seed(layout)
    task_id = _create_task(
        layout, parent=exp_id, name="t", contract=TaskContract(goal="x"),
    )
    begun = begin_run(layout, task=task_id)
    end_run(layout, run=begun.run_node_id)
    with pytest.raises(RunnerError, match="already ended"):
        end_run(layout, run=begun.run_node_id)


def test_end_rejects_non_bracket_run(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    result = exec_run(
        layout, command="true", parent="/research", name="plain-exec",
    )
    with pytest.raises(RunnerError, match="run begin"):
        end_run(layout, run=result.run_node_id)


def test_end_declared_failed_still_measures(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    exp_id = _seed(layout)
    task_id = _create_task(
        layout,
        parent=exp_id,
        name="t",
        contract=TaskContract(goal="x", allowed_outputs=["workspace/**"]),
    )
    begun = begin_run(layout, task=task_id)
    (tmp_path / "stray.txt").write_text("x\n", encoding="utf-8")
    ended = end_run(layout, run=begun.run_node_id, status="failed")
    assert ended.status == "failed"
    # Measurements are honest regardless of the human's claim.
    assert ended.contract_check is not None
    assert ended.contract_check.status == "out_of_scope"
    node = load_node(layout, begun.run_node_id)
    assert node.attrs["status"] == "failed"


def test_contract_judged_against_begin_snapshot(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    exp_id = _seed(layout)
    (tmp_path / "workspace").mkdir()
    task_id = _create_task(
        layout,
        parent=exp_id,
        name="frozen",
        contract=TaskContract(goal="x", allowed_outputs=["workspace/**"]),
    )
    begun = begin_run(layout, task=task_id)

    # Mutate the task mid-run: the live contract now allows nothing.
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                UpdateAttrsOp(target=task_id, attrs={"allowed_outputs": ["nothing/**"]}),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    (tmp_path / "workspace" / "new.py").write_text("ok\n", encoding="utf-8")

    ended = end_run(layout, run=begun.run_node_id)
    assert ended.contract_check is not None
    assert ended.contract_check.status == "passed"


def test_git_honesty_metadata_and_dirty_baseline_diff(tmp_path: Path) -> None:
    """`baseline_dirty` is recorded, and a file dirty at begin that changes
    again during the run still shows in the diff (snapshot comparison, not a
    porcelain set-difference)."""
    layout = init_project(tmp_path, with_scaffold=False).layout
    exp_id = _seed(layout)

    repo = tmp_path / "worktree"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "tracked.py").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    # Dirty *before* begin.
    (repo / "tracked.py").write_text("v2-dirty-at-begin\n", encoding="utf-8")

    task_id = _create_task(
        layout, parent=exp_id, name="t", contract=TaskContract(goal="x"),
    )
    begun = begin_run(layout, task=task_id, workdir=repo)
    node = load_node(layout, begun.run_node_id)
    assert isinstance(node.attrs["git_head"], str) and node.attrs["git_head"]
    assert node.attrs["baseline_dirty"] is True
    assert "tracked.py" in node.attrs["git_dirty_files"]

    # Changed *again* during the run — a porcelain set-difference would miss it.
    (repo / "tracked.py").write_text("v3-changed-in-run\n", encoding="utf-8")

    ended = end_run(layout, run=begun.run_node_id)
    assert [p for p in ended.files_modified if p.endswith("tracked.py")]


def test_doctor_flags_stale_running_bracket(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    exp_id = _seed(layout)
    task_id = _create_task(
        layout,
        parent=exp_id,
        name="tiny-budget",
        contract=TaskContract(goal="x", budget=BudgetSpec(time_seconds=0.01)),
    )
    begun = begin_run(layout, task=task_id)
    time.sleep(0.05)

    report = run_doctor(layout)
    stale = [i for i in report.issues if i.code == "stale_running_run"]
    assert len(stale) == 1
    assert begun.run_node_id in stale[0].message
    assert "run end" in stale[0].message

    end_run(layout, run=begun.run_node_id)
    assert run_doctor(layout).ok


def test_cli_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from simulanka.cli.app import app

    layout = init_project(tmp_path, with_scaffold=False).layout
    exp_id = _seed(layout)
    task_id = _create_task(
        layout,
        parent=exp_id,
        name="cli-task",
        contract=TaskContract(goal="x", allowed_outputs=["workspace/**"]),
    )
    monkeypatch.setenv("SIMULANKA_PROJECT", str(tmp_path))
    runner = CliRunner()

    begin_res = runner.invoke(app, ["run", "begin", "--task", task_id])
    assert begin_res.exit_code == 0, begin_res.output
    run_id = begin_res.output.splitlines()[0].strip()
    assert run_id.startswith("nod_")

    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "out.txt").write_text("ok\n", encoding="utf-8")

    end_res = runner.invoke(app, ["run", "end", run_id])
    assert end_res.exit_code == 0, end_res.output
    assert "passed" in end_res.output

    # Second end → runner error (exit 2).
    again = runner.invoke(app, ["run", "end", run_id])
    assert again.exit_code == 2
