"""Task contract: structured input for an agent attempt + post-hoc checks.

Lineage rule: each agent attempt creates a ``run`` with a ``fulfills`` edge to
the task and a *mirrored* snapshot of the contract attrs — editing the task
later does not retro-rewrite history.

This module is independent of the agent / runner layers and knows nothing of
``apply_patch``: it serializes contracts, matches paths, and executes the
acceptance command. The agent layer wires it together.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BudgetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_seconds: float | None = None


class AcceptanceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str


class TaskContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str
    allowed_outputs: list[str] = Field(
        default_factory=list,
        description=(
            "Gitignore-ish globs (relative to workdir) the agent may "
            "add/modify/delete. `*` does not cross `/`; `prefix/**` matches "
            "one+ levels below; `**/x` matches at any depth (zero+ levels). "
            "Empty = no scope check."
        ),
    )
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    acceptance: AcceptanceSpec | None = None

    def has_checks(self) -> bool:
        """True iff this contract triggers any check at runtime."""
        return bool(self.allowed_outputs) or self.acceptance is not None


def task_node_attrs(contract: TaskContract) -> dict[str, Any]:
    """Flatten a contract into the attrs dict stored on a ``task`` node."""
    return {
        "goal": contract.goal,
        "allowed_outputs": list(contract.allowed_outputs),
        "budget_time_seconds": contract.budget.time_seconds,
        "acceptance_command": (
            contract.acceptance.command if contract.acceptance is not None else None
        ),
    }


def contract_from_task_attrs(attrs: dict[str, Any]) -> TaskContract:
    """Reconstruct a contract from a task node's attrs dict."""
    goal = attrs.get("goal")
    if not isinstance(goal, str) or not goal:
        raise ValueError("task node is missing required string attr 'goal'.")
    allowed_raw = attrs.get("allowed_outputs") or []
    if not isinstance(allowed_raw, list):
        raise ValueError("task attr 'allowed_outputs' must be a list of strings.")
    budget_time = attrs.get("budget_time_seconds")
    if budget_time is not None and not isinstance(budget_time, int | float):
        raise ValueError("task attr 'budget_time_seconds' must be a number or null.")
    acceptance_cmd = attrs.get("acceptance_command")
    if acceptance_cmd is not None and not isinstance(acceptance_cmd, str):
        raise ValueError("task attr 'acceptance_command' must be a string or null.")
    return TaskContract(
        goal=goal,
        allowed_outputs=[str(p) for p in allowed_raw],
        budget=BudgetSpec(
            time_seconds=float(budget_time) if budget_time is not None else None,
        ),
        acceptance=(
            AcceptanceSpec(command=acceptance_cmd)
            if acceptance_cmd is not None
            else None
        ),
    )


def write_contract_snapshot(
    run_dir: Path, *, task_node_id: str, contract: TaskContract,
) -> Path:
    """Persist the resolved contract into ``<run_dir>/contract.json`` for audit.

    Every bracket that fulfills a task writes this snapshot at launch; checks
    at close time read it back — never the live task node — so editing the
    task later cannot retro-rewrite what a run is judged against.
    """
    contract_path = run_dir / "contract.json"
    contract_path.write_text(
        json.dumps(
            {"task_node_id": task_node_id, **contract.model_dump()},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return contract_path


def load_contract_snapshot(run_dir: Path) -> tuple[str, TaskContract]:
    """Read back a ``contract.json`` snapshot. Returns (task_node_id, contract)."""
    raw = json.loads((run_dir / "contract.json").read_text(encoding="utf-8"))
    task_node_id = str(raw.pop("task_node_id", ""))
    return task_node_id, TaskContract.model_validate(raw)


_GLOB_CACHE: dict[str, re.Pattern[str]] = {}


def _compile_glob(pattern: str) -> re.Pattern[str]:
    cached = _GLOB_CACHE.get(pattern)
    if cached is not None:
        return cached
    parts = pattern.split("/")
    pieces: list[str] = []
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        if part == "**":
            if is_last:
                # `prefix/**` matches one or more components below.
                pieces.append(".+")
            else:
                # `.../**/something` matches zero or more components.
                pieces.append("(?:.+/)?")
                continue  # skip the separator that would normally follow
        else:
            sub: list[str] = []
            for c in part:
                if c == "*":
                    sub.append("[^/]*")
                elif c == "?":
                    sub.append("[^/]")
                else:
                    sub.append(re.escape(c))
            pieces.append("".join(sub))
        if not is_last:
            pieces.append("/")
    regex = re.compile("^" + "".join(pieces) + "$")
    _GLOB_CACHE[pattern] = regex
    return regex


def glob_match_any(path: str, patterns: list[str]) -> bool:
    return any(_compile_glob(p).match(path) is not None for p in patterns)


ContractStatus = Literal["passed", "out_of_scope", "acceptance_failed"]


@dataclass(frozen=True)
class ContractCheckResult:
    status: ContractStatus
    out_of_scope_files: list[str]
    acceptance_exit_code: int | None
    acceptance_log_path: str | None  # relative to layout.root, or None


def check_contract(
    contract: TaskContract,
    *,
    diff: dict[str, list[str]],
    workdir: Path,
    acceptance_log_dest: Path,
    layout_root: Path,
) -> ContractCheckResult:
    """Validate a contract against the diff + optionally run the acceptance command.

    Callers should gate this on ``contract.has_checks()`` — invoking it on a
    contract with no checks is a programming error (the result would carry no
    information).
    """
    if not contract.has_checks():
        raise ValueError(
            "check_contract called on a contract with no checks; "
            "gate with contract.has_checks() first.",
        )

    out_of_scope = sorted(
        path for path in {
            *diff.get("added", []),
            *diff.get("modified", []),
            *diff.get("deleted", []),
        }
        if contract.allowed_outputs and not glob_match_any(path, contract.allowed_outputs)
    )

    acceptance_exit: int | None = None
    log_rel: str | None = None
    if contract.acceptance is not None:
        proc = subprocess.run(
            ["sh", "-c", contract.acceptance.command],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            check=False,
        )
        acceptance_log_dest.write_text(
            (
                f"$ {contract.acceptance.command}\n"
                f"--- stdout ---\n{proc.stdout}\n"
                f"--- stderr ---\n{proc.stderr}\n"
                f"--- exit_code ---\n{proc.returncode}\n"
            ),
            encoding="utf-8",
        )
        acceptance_exit = proc.returncode
        log_rel = str(acceptance_log_dest.relative_to(layout_root)).replace("\\", "/")

    if out_of_scope:
        status: ContractStatus = "out_of_scope"
    elif acceptance_exit is not None and acceptance_exit != 0:
        status = "acceptance_failed"
    else:
        status = "passed"

    return ContractCheckResult(
        status=status,
        out_of_scope_files=out_of_scope,
        acceptance_exit_code=acceptance_exit,
        acceptance_log_path=log_rel,
    )
