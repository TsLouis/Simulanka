"""The execution bracket: ``run begin`` / ``run end``.

The system measures at the two ends and stays out of the middle — whether a
human or an agent does the work between ``begin`` and ``end`` is deliberately
not modeled. ``begin`` records the baseline (workspace snapshot, mirrored
contract, git honesty metadata) and commits the run as ``status=running``;
``end`` re-snapshots, diffs, runs the acceptance command from the launch-time
contract snapshot, and closes the run.

Differences from the exec/agent paths:

* No subprocess: there is no command, no exit_code, and no stdout/stderr file
  nodes — the human works in their own terminal, and the system does not
  pretend to have captured what it cannot see.
* No "current run" ambient state: ``begin`` prints the run id and the caller
  (human or harness) holds on to it.
* All intents use ``actor="system"`` — measurement belongs to the system.

Concurrency note: two brackets over the same workdir will see each other's
edits in their diffs. v1 does not guard against this; the worktree-per-run
convention keeps brackets isolated in practice.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ulid import ULID

from simulanka.contract import (
    ContractCheckResult,
    TaskContract,
    check_contract,
    contract_from_task_attrs,
    load_contract_snapshot,
    task_node_attrs,
    write_contract_snapshot,
)
from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp, UpdateAttrsOp
from simulanka.kernel.resolver import resolve_node
from simulanka.layout.project import ProjectLayout
from simulanka.runner.exec import RunnerError, _maybe_relative, _resolve_parent
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import load_node
from simulanka.workspace import diff_snapshots, snapshot_workspace

_SYSTEM_ACTOR = "system"


@dataclass(frozen=True)
class BeginResult:
    run_node_id: str
    run_dir: Path
    task_node_id: str
    workdir: Path
    snapshot_files: int
    git_head: str | None
    baseline_dirty: bool | None  # None = workdir is not a git repo


@dataclass(frozen=True)
class EndResult:
    run_node_id: str
    status: str
    duration_seconds: float
    changes_path: str
    files_added: list[str]
    files_modified: list[str]
    files_deleted: list[str]
    contract_check: ContractCheckResult | None


def begin_run(
    layout: ProjectLayout,
    *,
    task: str,
    parent: str | None = None,
    name: str | None = None,
    workdir: Path | None = None,
) -> BeginResult:
    """Open an execution bracket against *task* and commit it as ``running``.

    Baseline recording:

    * ``<run_dir>/snapshot.json`` — ``{path: hash}`` for every file under the
      workdir. This is the diff mechanism: ``end`` re-snapshots and compares,
      which catches files that were already dirty at begin and changed again
      during the run (a porcelain set-difference would miss them).
    * git HEAD + dirty-file list — honesty metadata only, recorded when the
      workdir is a git repo. Never used to compute the diff.
    * ``<run_dir>/contract.json`` — the mirrored contract; ``end`` judges
      against this snapshot, not the live task node.

    ``parent`` defaults to the task's own parent (its experiment).
    """
    task_node = _resolve_task(layout, task)
    contract = contract_from_task_attrs(task_node.attrs)

    if parent is not None:
        parent_node = _resolve_parent(layout, parent)
    else:
        if task_node.parent_id is None:
            raise RunnerError(
                f"task {task_node.id} has no parent; pass --parent explicitly."
            )
        parent_node = load_node(layout, task_node.parent_id)

    run_handle = str(ULID())
    run_dir = layout.dot_dir / "runs" / run_handle
    run_dir.mkdir(parents=True, exist_ok=True)
    run_name = name or f"run-{run_handle}"

    effective_workdir = (workdir or layout.root).resolve()
    if not effective_workdir.is_dir():
        raise RunnerError(f"--workdir {effective_workdir} is not a directory.")

    files = snapshot_workspace([effective_workdir])
    snapshot_path = run_dir / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {"workdir": str(effective_workdir), "files": files},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    write_contract_snapshot(run_dir, task_node_id=task_node.id, contract=contract)

    started_at = datetime.now(timezone.utc)
    run_attrs: dict[str, object] = {
        "status": "running",
        "started_at": started_at.isoformat(),
        "ended_at": None,
        "duration_seconds": None,
        "workdir": _maybe_relative(effective_workdir, layout.root),
        "run_handle": run_handle,
        "bracket": True,
        "contract": {
            "task_node_id": task_node.id,
            **task_node_attrs(contract),
        },
    }

    git_head, dirty_files = _git_baseline(effective_workdir)
    if git_head is not None:
        run_attrs["git_head"] = git_head
        run_attrs["baseline_dirty"] = bool(dirty_files)
        if dirty_files:
            run_attrs["git_dirty_files"] = dirty_files

    receipt = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(
                type="run",
                name=run_name,
                parent=parent_node.id,
                attrs=run_attrs,
                ref="run",
            ),
            CreateEdgeOp(type="fulfills", source="@run", target=task_node.id),
        ],
        actor=_SYSTEM_ACTOR,
        note=f"run begin: {run_name} fulfills task {task_node.name}",
    )
    [run_node_id] = receipt.nodes

    return BeginResult(
        run_node_id=run_node_id,
        run_dir=run_dir,
        task_node_id=task_node.id,
        workdir=effective_workdir,
        snapshot_files=len(files),
        git_head=git_head,
        baseline_dirty=bool(dirty_files) if git_head is not None else None,
    )


def end_run(
    layout: ProjectLayout,
    *,
    run: str,
    status: str = "done",
) -> EndResult:
    """Close a bracket: diff against the begin snapshot, check the contract, seal the run.

    ``status`` is the caller's claim about the work (``done``/``failed``); the
    measurements (diff, acceptance) run the same either way. A run that has
    already ended is rejected — history is not rewritten.
    """
    if status not in ("done", "failed"):
        raise RunnerError(f"--status must be `done` or `failed`, got {status!r}.")

    run_node = _resolve_bracket_run(layout, run)
    if run_node.attrs.get("status") != "running":
        raise RunnerError(
            f"run {run_node.id} already ended "
            f"(status={run_node.attrs.get('status')!r})."
        )

    run_handle = str(run_node.attrs["run_handle"])
    run_dir = layout.dot_dir / "runs" / run_handle

    snapshot_raw = json.loads(
        (run_dir / "snapshot.json").read_text(encoding="utf-8"),
    )
    workdir = Path(str(snapshot_raw["workdir"]))
    before: dict[str, str] = {
        str(k): str(v) for k, v in snapshot_raw["files"].items()
    }

    after = snapshot_workspace([workdir])
    diff = diff_snapshots(before, after, base=layout.root)
    changes_path = run_dir / "changes.json"
    changes_path.write_text(
        json.dumps({"workdir": str(workdir), **diff}, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    task_node_id, contract = load_contract_snapshot(run_dir)
    contract_check = _check_bracket_contract(
        contract, diff=diff, workdir=workdir, run_dir=run_dir, layout=layout,
    )

    started_at = datetime.fromisoformat(
        str(run_node.attrs["started_at"]).replace("Z", "+00:00"),
    )
    ended_at = datetime.now(timezone.utc)
    duration = (ended_at - started_at).total_seconds()

    final_attrs: dict[str, object] = {
        "status": status,
        "ended_at": ended_at.isoformat(),
        "duration_seconds": duration,
    }
    if contract_check is not None:
        final_attrs["contract_check"] = {
            "status": contract_check.status,
            "out_of_scope_files": list(contract_check.out_of_scope_files),
            "acceptance_exit_code": contract_check.acceptance_exit_code,
            "acceptance_log_path": contract_check.acceptance_log_path,
        }

    apply_patch_now(
        layout,
        ops=[UpdateAttrsOp(target=run_node.id, attrs=final_attrs)],
        actor=_SYSTEM_ACTOR,
        note=f"run end: {run_node.name} -> {status}",
    )

    return EndResult(
        run_node_id=run_node.id,
        status=status,
        duration_seconds=duration,
        changes_path=str(changes_path.relative_to(layout.root)),
        files_added=diff["added"],
        files_modified=diff["modified"],
        files_deleted=diff["deleted"],
        contract_check=contract_check,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_task(layout: ProjectLayout, selector: str) -> Node:
    try:
        node = resolve_node(layout, selector)
    except ValueError as exc:
        raise RunnerError(f"--task {selector!r}: {exc}") from exc
    if node.type != "task":
        raise RunnerError(
            f"--task {selector!r}: node is type `{node.type}`, not `task`."
        )
    return node


def _resolve_bracket_run(layout: ProjectLayout, selector: str) -> Node:
    try:
        node = resolve_node(layout, selector)
    except ValueError as exc:
        raise RunnerError(f"run selector {selector!r}: {exc}") from exc
    if node.type != "run":
        raise RunnerError(
            f"{selector!r}: node is type `{node.type}`, not `run`."
        )
    if node.attrs.get("bracket") is not True:
        raise RunnerError(
            f"run {node.id} was not opened with `run begin` "
            "(exec/agent runs close themselves)."
        )
    return node


def _check_bracket_contract(
    contract: TaskContract,
    *,
    diff: dict[str, list[str]],
    workdir: Path,
    run_dir: Path,
    layout: ProjectLayout,
) -> ContractCheckResult | None:
    if not contract.has_checks():
        return None
    return check_contract(
        contract,
        diff=diff,
        workdir=workdir,
        acceptance_log_dest=run_dir / "acceptance.log",
        layout_root=layout.root,
    )


def _git_baseline(workdir: Path) -> tuple[str | None, list[str]]:
    """Return (HEAD sha, dirty file list) for *workdir*, or (None, []) outside git.

    Honesty metadata only — file granularity via ``git status --porcelain
    -uall``. The bracket's diff never depends on git.
    """
    try:
        head = subprocess.run(
            ["git", "-C", str(workdir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None, []
    if head.returncode != 0:
        return None, []

    status = subprocess.run(
        ["git", "-C", str(workdir), "status", "--porcelain", "-uall"],
        capture_output=True,
        text=True,
        check=False,
    )
    dirty = [
        line[3:].strip()
        for line in status.stdout.splitlines()
        if len(line) > 3
    ]
    return head.stdout.strip(), dirty
