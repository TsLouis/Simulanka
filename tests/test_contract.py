"""Task contract: model, glob matcher, check_contract."""

from __future__ import annotations

from pathlib import Path

from simulanka.contract import (
    AcceptanceSpec,
    BudgetSpec,
    TaskContract,
    check_contract,
    contract_from_task_attrs,
    glob_match_any,
    task_node_attrs,
)


def test_contract_roundtrips_through_task_attrs() -> None:
    contract = TaskContract(
        goal="optimize loader",
        allowed_outputs=["src/data/**", "tests/test_data.py"],
        budget=BudgetSpec(time_seconds=600),
        acceptance=AcceptanceSpec(command="pytest -q tests/test_data.py"),
    )
    attrs = task_node_attrs(contract)
    back = contract_from_task_attrs(attrs)
    assert back == contract


def test_contract_attrs_minimum() -> None:
    """Goal-only is a valid contract."""
    contract = TaskContract(goal="explore the codebase")
    back = contract_from_task_attrs(task_node_attrs(contract))
    assert back.goal == "explore the codebase"
    assert back.allowed_outputs == []
    assert back.budget.time_seconds is None
    assert back.acceptance is None


def test_glob_match_basic_patterns() -> None:
    # exact
    assert glob_match_any("src/foo.py", ["src/foo.py"])
    assert not glob_match_any("src/bar.py", ["src/foo.py"])
    # single * does not cross /
    assert glob_match_any("src/foo.py", ["src/*.py"])
    assert not glob_match_any("src/sub/foo.py", ["src/*.py"])
    # trailing /** matches one or more levels below
    assert glob_match_any("src/foo.py", ["src/**"])
    assert glob_match_any("src/sub/deep/foo.py", ["src/**"])
    assert not glob_match_any("other.py", ["src/**"])
    # /**/ matches zero or more directories
    assert glob_match_any("src/foo.py", ["src/**/*.py"])
    assert glob_match_any("src/a/foo.py", ["src/**/*.py"])
    assert glob_match_any("src/a/b/foo.py", ["src/**/*.py"])
    # leading **/ matches at any depth
    assert glob_match_any("foo.py", ["**/*.py"])
    assert glob_match_any("a/b/foo.py", ["**/*.py"])


def test_check_contract_rejects_no_check_contract(tmp_path: Path) -> None:
    """has_checks() gating is the caller's responsibility."""
    import pytest
    contract = TaskContract(goal="just do it")
    assert not contract.has_checks()
    with pytest.raises(ValueError):
        check_contract(
            contract,
            diff={"added": ["a.txt"], "modified": [], "deleted": []},
            workdir=tmp_path,
            acceptance_log_dest=tmp_path / "_.log",
            layout_root=tmp_path,
        )


def test_check_contract_passed(tmp_path: Path) -> None:
    contract = TaskContract(
        goal="x", allowed_outputs=["src/**"],
    )
    result = check_contract(
        contract,
        diff={
            "added": ["src/new.py"],
            "modified": ["src/sub/old.py"],
            "deleted": [],
        },
        workdir=tmp_path,
        acceptance_log_dest=tmp_path / "_.log",
        layout_root=tmp_path,
    )
    assert result.status == "passed"
    assert result.out_of_scope_files == []


def test_check_contract_flags_out_of_scope(tmp_path: Path) -> None:
    contract = TaskContract(
        goal="x", allowed_outputs=["src/**"],
    )
    result = check_contract(
        contract,
        diff={
            "added": ["src/new.py", "secrets.env"],
            "modified": ["src/x.py", "config/global.yaml"],
            "deleted": [],
        },
        workdir=tmp_path,
        acceptance_log_dest=tmp_path / "_.log",
        layout_root=tmp_path,
    )
    assert result.status == "out_of_scope"
    assert result.out_of_scope_files == ["config/global.yaml", "secrets.env"]


def test_check_contract_runs_acceptance(tmp_path: Path) -> None:
    contract = TaskContract(
        goal="x",
        allowed_outputs=["**"],  # everything allowed; isolate acceptance behavior
        acceptance=AcceptanceSpec(command="true"),
    )
    log_dest = tmp_path / "acceptance.log"
    result = check_contract(
        contract,
        diff={"added": [], "modified": [], "deleted": []},
        workdir=tmp_path,
        acceptance_log_dest=log_dest,
        layout_root=tmp_path,
    )
    assert result.status == "passed"
    assert result.acceptance_exit_code == 0
    assert log_dest.exists()
    assert result.acceptance_log_path == "acceptance.log"


def test_check_contract_acceptance_failure_overrides_pass(tmp_path: Path) -> None:
    contract = TaskContract(
        goal="x",
        allowed_outputs=["**"],
        acceptance=AcceptanceSpec(command="exit 7"),
    )
    result = check_contract(
        contract,
        diff={"added": [], "modified": [], "deleted": []},
        workdir=tmp_path,
        acceptance_log_dest=tmp_path / "acceptance.log",
        layout_root=tmp_path,
    )
    assert result.status == "acceptance_failed"
    assert result.acceptance_exit_code == 7


def test_check_contract_out_of_scope_beats_acceptance(tmp_path: Path) -> None:
    """Scope violations are higher-priority than acceptance results."""
    contract = TaskContract(
        goal="x",
        allowed_outputs=["src/**"],
        acceptance=AcceptanceSpec(command="true"),  # would pass
    )
    result = check_contract(
        contract,
        diff={"added": ["evil.sh"], "modified": [], "deleted": []},
        workdir=tmp_path,
        acceptance_log_dest=tmp_path / "acceptance.log",
        layout_root=tmp_path,
    )
    assert result.status == "out_of_scope"
    assert result.out_of_scope_files == ["evil.sh"]
    # Acceptance still ran (we capture the exit code regardless), but status
    # surfaces the more serious violation.
    assert result.acceptance_exit_code == 0
