"""Detached (asynchronous) agent execution.

Layered on top of :mod:`simulanka.runner.detached`: launches the agent via the
runner's ``start_run`` and persists the *before* workspace snapshot so the diff
can be computed lazily at reconcile time. The runner stays agent-agnostic —
snapshots and ``changes.json`` are agent-layer concerns and the runner doesn't
grow hooks for them.

Finalization is idempotent and only kicks in for runs that have an
``agent_meta.json`` in their ``run_dir``; the CLI calls it after each
reconcile. No background watcher.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from simulanka.agent.wrapper import (
    _check_attrs,
    _diff,
    _fill,
    _resolve_prompt_and_contract,
    _resolve_scope,
    _resolve_template,
    _snapshot,
    write_contract_snapshot,
)
from simulanka.contract import (
    ContractCheckResult,
    TaskContract,
    check_contract,
    task_node_attrs,
)
from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateEdgeOp, UpdateAttrsOp
from simulanka.layout.project import ProjectLayout
from simulanka.runner import start_run
from simulanka.schema.entities import Node


@dataclass(frozen=True)
class AgentStartResult:
    run_node_id: str
    pid: int
    run_dir: Path
    prompt_path: str
    agent_meta_path: str
    task_node_id: str | None = None


@dataclass(frozen=True)
class AgentDiffSummary:
    changes_path: str
    added: list[str]
    modified: list[str]
    deleted: list[str]
    contract_check: ContractCheckResult | None = None


def start_agent_run(
    layout: ProjectLayout,
    *,
    agent: str,
    prompt: str | None = None,
    task_node_id: str | None = None,
    parent: str,
    name: str,
    workdir: Path | None = None,
    extra_args: list[str] | None = None,
    track_scope: list[str] | None = None,
    actor: str = "agent:detached",
) -> AgentStartResult:
    """Snapshot the workspace, launch the agent detached, persist meta for reconcile.

    Exactly one of ``prompt`` or ``task_node_id`` must be given (see
    :func:`simulanka.agent.run_agent`). The contract (if any) is mirrored onto
    the run node immediately; the ``allowed_outputs`` / ``acceptance`` checks
    run lazily in :func:`finalize_agent_diff`.

    ``contract.budget.time_seconds`` is recorded but *not* enforced — detached
    runs have no timeout (use ``run kill``).
    """
    import shlex

    resolved_prompt, contract = _resolve_prompt_and_contract(layout, prompt, task_node_id)

    template = _resolve_template(agent)
    argv = [_fill(part, resolved_prompt) for part in template]
    if extra_args:
        argv.extend(extra_args)
    command = shlex.join(argv)

    effective_workdir = (workdir or layout.root).resolve()
    scope_dirs = _resolve_scope(effective_workdir, track_scope)
    before = _snapshot(scope_dirs)

    started = start_run(
        layout,
        command=command,
        parent=parent,
        name=name,
        workdir=effective_workdir,
        agent=agent,
        actor=actor,
    )

    run_dir = started.run_dir
    (run_dir / "before_snapshot.json").write_text(
        json.dumps(before, indent=2, sort_keys=True), encoding="utf-8",
    )
    meta_path = run_dir / "agent_meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "agent": agent,
                "argv": argv,
                "workdir": str(effective_workdir),
                "track_scope": [str(p) for p in scope_dirs],
                "task_node_id": task_node_id,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    prompt_path = run_dir / "prompt.txt"
    prompt_path.write_text(resolved_prompt, encoding="utf-8")

    if contract is not None and task_node_id is not None:
        write_contract_snapshot(run_dir, task_node_id=task_node_id, contract=contract)
        apply_patch_now(
            layout,
            ops=[
                UpdateAttrsOp(
                    target=started.run_node_id,
                    attrs={
                        "contract": {
                            "task_node_id": task_node_id,
                            **task_node_attrs(contract),
                        },
                    },
                ),
                CreateEdgeOp(
                    type="fulfills",
                    source=started.run_node_id,
                    target=task_node_id,
                ),
            ],
            actor=actor,
            note=f"agent: fulfills task {task_node_id}",
        )

    return AgentStartResult(
        run_node_id=started.run_node_id,
        pid=started.pid,
        run_dir=run_dir,
        prompt_path=str(prompt_path.relative_to(layout.root)),
        agent_meta_path=str(meta_path.relative_to(layout.root)),
        task_node_id=task_node_id,
    )


def finalize_agent_diff(
    layout: ProjectLayout, run_node: Node,
) -> AgentDiffSummary | None:
    """Compute (or recall) the workspace diff for a finished agent run.

    Returns ``None`` when:

    * the node has no ``agent_meta.json`` in its run dir (not an agent run, or
      was started by the sync wrapper which writes ``changes.json`` directly), or
    * the run is still ``running`` (caller should reconcile first).

    Otherwise writes ``changes.json`` (if not already present) and returns a
    summary. Idempotent — subsequent calls reparse the existing
    ``changes.json`` without re-hashing. When the run has a contract attached
    (``task_node_id`` in meta), the contract check is also executed and the
    result is mirrored onto the run node's ``contract_check`` attr.
    """
    run_handle = run_node.attrs.get("run_handle")
    if not isinstance(run_handle, str):
        return None
    run_dir = layout.dot_dir / "runs" / run_handle
    meta_path = run_dir / "agent_meta.json"
    if not meta_path.exists():
        return None
    if run_node.attrs.get("status") == "running":
        return None

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    task_node_id = meta.get("task_node_id")
    changes_path = run_dir / "changes.json"
    diff: dict[str, list[str]]

    if changes_path.exists():
        existing = json.loads(changes_path.read_text(encoding="utf-8"))
        diff = {
            "added": list(existing.get("added", [])),
            "modified": list(existing.get("modified", [])),
            "deleted": list(existing.get("deleted", [])),
        }
    else:
        before_raw = json.loads(
            (run_dir / "before_snapshot.json").read_text(encoding="utf-8"),
        )
        if not isinstance(before_raw, dict):
            raise RuntimeError(
                f"before_snapshot.json in {run_dir} is malformed (expected object).",
            )
        before: dict[str, str] = {str(k): str(v) for k, v in before_raw.items()}
        scope_dirs = [Path(p) for p in meta.get("track_scope", [])]
        after = _snapshot(scope_dirs)
        diff = _diff(before, after, base=layout.root)
        changes_path.write_text(
            json.dumps(
                {
                    "agent": meta.get("agent"),
                    "argv": meta.get("argv"),
                    "workdir": meta.get("workdir"),
                    "track_scope": meta.get("track_scope"),
                    **diff,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    contract_check: ContractCheckResult | None = None
    if (
        isinstance(task_node_id, str)
        and not isinstance(run_node.attrs.get("contract_check"), dict)
    ):
        contract_check = _run_contract_check(
            layout,
            run_node_id=run_node.id,
            run_dir=run_dir,
            workdir=Path(str(meta.get("workdir"))),
            diff=diff,
        )

    return AgentDiffSummary(
        changes_path=str(changes_path.relative_to(layout.root)),
        added=diff["added"],
        modified=diff["modified"],
        deleted=diff["deleted"],
        contract_check=contract_check,
    )


def _run_contract_check(
    layout: ProjectLayout,
    *,
    run_node_id: str,
    run_dir: Path,
    workdir: Path,
    diff: dict[str, list[str]],
) -> ContractCheckResult | None:
    """Check the launch-time contract snapshot, persist the result.

    The contract comes from ``<run_dir>/contract.json`` written at launch —
    *not* from the live task node, so editing the task after launch cannot
    retro-rewrite what this run is judged against.

    Returns ``None`` if the contract has no checks configured. The acceptance
    command (when configured) runs **synchronously** in this process — i.e. in
    the host CLI invocation that triggered finalize. A ``simulanka run wait``
    on a task-bound detached run will therefore block on the acceptance
    command's runtime.
    """
    contract_path = run_dir / "contract.json"
    try:
        raw = json.loads(contract_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"contract.json missing in {run_dir}; the run references a task "
            f"but has no launch-time contract snapshot.",
        ) from exc
    raw.pop("task_node_id", None)
    contract = TaskContract.model_validate(raw)
    if not contract.has_checks():
        return None
    result = check_contract(
        contract,
        diff=diff,
        workdir=workdir,
        acceptance_log_dest=run_dir / "acceptance.log",
        layout_root=layout.root,
    )
    apply_patch_now(
        layout,
        ops=[UpdateAttrsOp(target=run_node_id, attrs=_check_attrs(result))],
        actor="agent:contract",
        note=f"contract_check {result.status}",
    )
    return result
