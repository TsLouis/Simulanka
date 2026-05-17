"""End-to-end TaskContract integration: task node + run agent + contract check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulanka.agent import (
    AcceptanceSpec,
    BudgetSpec,
    TaskContract,
    finalize_agent_diff,
    run_agent,
    start_agent_run,
)
from simulanka.contract import task_node_attrs
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.runner import wait_run
from simulanka.storage.entity_store import iter_edges, load_node
from tests.conftest import fake_argv as _fake_argv


def _seed_dir(layout: ProjectLayout) -> None:
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="research")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )


def _create_task(layout: ProjectLayout, *, name: str, contract: TaskContract) -> str:
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(
                    type="task",
                    name=name,
                    parent="/research",
                    attrs=task_node_attrs(contract),
                ),
            ],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    [task_id] = receipt.nodes
    return task_id


def test_sync_agent_with_task_records_contract_and_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_dir(layout)

    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "existing.py").write_text("old\n", encoding="utf-8")

    task_id = _create_task(
        layout,
        name="touch-src",
        contract=TaskContract(
            goal="modify src",
            allowed_outputs=["workspace/**"],
            budget=BudgetSpec(time_seconds=30),
            acceptance=AcceptanceSpec(command="test -f workspace/new.py"),
        ),
    )
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        _fake_argv(
            f"echo touched > {tmp_path}/workspace/new.py; "
            f"echo bumped > {tmp_path}/workspace/existing.py"
        ),
    )

    result = run_agent(
        layout,
        agent="fake",
        task_node_id=task_id,
        parent="/research",
        name="attempt1",
    )
    assert result.status == "done"
    assert result.task_node_id == task_id
    assert result.contract_check is not None
    assert result.contract_check.status == "passed"
    assert result.contract_check.acceptance_exit_code == 0

    # Run node carries the mirrored contract + check.
    run_node = load_node(layout, result.run_node_id)
    assert run_node.attrs["contract"]["task_node_id"] == task_id
    assert run_node.attrs["contract"]["allowed_outputs"] == ["workspace/**"]
    assert run_node.attrs["contract_check"]["status"] == "passed"

    # `fulfills` edge exists.
    fulfills = [
        e for e in iter_edges(layout)
        if e.type == "fulfills" and e.source_id == result.run_node_id
    ]
    assert len(fulfills) == 1
    assert fulfills[0].target_id == task_id

    # Snapshot artifact persisted next to changes.json/prompt.txt.
    contract_path = layout.dot_dir / "runs" / str(run_node.attrs["run_handle"]) / "contract.json"
    snap = json.loads(contract_path.read_text(encoding="utf-8"))
    assert snap["task_node_id"] == task_id
    assert snap["goal"] == "modify src"

    assert run_doctor(layout).ok


def test_sync_agent_flags_out_of_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_dir(layout)

    task_id = _create_task(
        layout,
        name="src-only",
        contract=TaskContract(goal="x", allowed_outputs=["workspace/**"]),
    )
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        _fake_argv(
            f"mkdir -p {tmp_path}/workspace && echo ok > {tmp_path}/workspace/legit.txt; "
            f"echo leaked > {tmp_path}/secret.txt"
        ),
    )
    result = run_agent(
        layout,
        agent="fake",
        task_node_id=task_id,
        parent="/research",
        name="violator",
    )
    assert result.status == "done"
    assert result.contract_check is not None
    assert result.contract_check.status == "out_of_scope"
    assert "secret.txt" in result.contract_check.out_of_scope_files
    assert "workspace/legit.txt" not in result.contract_check.out_of_scope_files


def test_sync_agent_acceptance_failure_records_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_dir(layout)
    task_id = _create_task(
        layout,
        name="must-pass-test",
        contract=TaskContract(
            goal="x",
            allowed_outputs=["**"],
            acceptance=AcceptanceSpec(command="exit 1"),
        ),
    )
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        _fake_argv(f"echo done > {tmp_path}/marker.txt"),
    )
    result = run_agent(
        layout,
        agent="fake",
        task_node_id=task_id,
        parent="/research",
        name="failed-accept",
    )
    assert result.contract_check is not None
    assert result.contract_check.status == "acceptance_failed"
    assert result.contract_check.acceptance_exit_code == 1
    # acceptance.log should be persisted.
    assert result.contract_check.acceptance_log_path is not None
    log_text = (layout.root / result.contract_check.acceptance_log_path).read_text(
        encoding="utf-8",
    )
    assert "exit_code" in log_text


def test_prompt_and_task_mutually_exclusive(tmp_path: Path) -> None:
    from simulanka.agent import AgentError

    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_dir(layout)
    task_id = _create_task(
        layout, name="t", contract=TaskContract(goal="x"),
    )
    with pytest.raises(AgentError):
        run_agent(
            layout,
            agent="fake",
            prompt="extra",
            task_node_id=task_id,
            parent="/research",
            name="bad",
        )
    with pytest.raises(AgentError):
        run_agent(
            layout, agent="fake", parent="/research", name="bad2",
        )


def test_detached_agent_with_task_lazily_checks_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_dir(layout)
    (tmp_path / "workspace").mkdir()
    task_id = _create_task(
        layout,
        name="async-task",
        contract=TaskContract(
            goal="touch src",
            allowed_outputs=["workspace/**"],
            acceptance=AcceptanceSpec(command="test -f workspace/new.py"),
        ),
    )
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        _fake_argv(f"echo created > {tmp_path}/workspace/new.py"),
    )

    started = start_agent_run(
        layout,
        agent="fake",
        task_node_id=task_id,
        parent="/research",
        name="async-attempt",
    )
    assert started.task_node_id == task_id
    # Contract mirrored immediately.
    early_node = load_node(layout, started.run_node_id)
    assert early_node.attrs["contract"]["task_node_id"] == task_id
    assert "contract_check" not in early_node.attrs

    finished = wait_run(
        layout, started.run_node_id, timeout=10.0, poll_interval=0.05,
    )
    assert finished.attrs["status"] == "done"

    summary = finalize_agent_diff(layout, finished)
    assert summary is not None
    assert summary.contract_check is not None
    assert summary.contract_check.status == "passed"

    # Contract_check persisted on the run node.
    final_node = load_node(layout, started.run_node_id)
    assert final_node.attrs["contract_check"]["status"] == "passed"

    # Re-finalize should NOT re-run acceptance (idempotent via attr presence).
    summary2 = finalize_agent_diff(layout, final_node)
    assert summary2 is not None
    # contract_check is None on the second call because the run node already
    # has it — we don't re-execute the acceptance command.
    assert summary2.contract_check is None

    assert run_doctor(layout).ok


def test_detached_agent_out_of_scope_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_dir(layout)
    task_id = _create_task(
        layout,
        name="strict",
        contract=TaskContract(goal="x", allowed_outputs=["workspace/**"]),
    )
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        _fake_argv(f"echo leaked > {tmp_path}/outside.txt"),
    )
    started = start_agent_run(
        layout,
        agent="fake",
        task_node_id=task_id,
        parent="/research",
        name="async-violator",
    )
    finished = wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.05)
    summary = finalize_agent_diff(layout, finished)
    assert summary is not None
    assert summary.contract_check is not None
    assert summary.contract_check.status == "out_of_scope"
    assert "outside.txt" in summary.contract_check.out_of_scope_files


def test_free_form_prompt_still_works_without_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed_dir(layout)
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        _fake_argv(f"echo hi > {tmp_path}/note.txt"),
    )
    result = run_agent(
        layout,
        agent="fake",
        prompt="just a free-form prompt",
        parent="/research",
        name="freeform",
    )
    assert result.status == "done"
    assert result.task_node_id is None
    assert result.contract_check is None
    # Run node has no contract attrs.
    run_node = load_node(layout, result.run_node_id)
    assert "contract" not in run_node.attrs
    assert "contract_check" not in run_node.attrs
