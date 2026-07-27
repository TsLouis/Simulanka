"""``simulanka run`` — execute commands and record them as ``run`` nodes.

Exit codes (POSIX-style, single source of truth):

* ``0`` — success: run completed with status=done (and contract passed, if any).
* ``1`` — the run itself failed: status=failed / timed_out / exit_code != 0.
* ``2`` — caller / runtime error: bad selector, runner error, wait timeout,
  or a detached run is still ``running`` when ``status`` is queried.
* ``3`` — contract violation: run finished but ``contract_check.status`` is
  ``out_of_scope`` or ``acceptance_failed``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from simulanka.agent import (
    AgentDiffSummary,
    AgentError,
    finalize_agent_diff,
    run_agent,
    start_agent_run,
)
from simulanka.cli.actor import ActorOption, resolve_actor
from simulanka.kernel.resolver import resolve_node
from simulanka.layout.project import ProjectLayout
from simulanka.runner import (
    RunnerError,
    RunNotFound,
    begin_run,
    end_run,
    exec_run,
    kill_run,
    reconcile_run,
    start_run,
    wait_run,
)
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import iter_nodes

run_app = typer.Typer(help="Execute commands and capture them in the graph.", no_args_is_help=True)


@run_app.command("exec")
def run_exec(
    command: Annotated[
        str,
        typer.Option(
            "--cmd",
            "-c",
            help="Shell command to run (passed to `sh -c`).",
        ),
    ],
    parent: Annotated[
        str,
        typer.Option(
            "--parent",
            "-p",
            help="Selector of the directory or experiment that owns this run.",
        ),
    ],
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Name for the run node (unique within parent)."),
    ],
    workdir: Annotated[
        Path | None,
        typer.Option(
            "--workdir",
            "-w",
            help="Subprocess working directory. Defaults to the project root.",
        ),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", "-t", help="Seconds before the run is killed."),
    ] = None,
    agent: Annotated[
        str,
        typer.Option(
            "--agent",
            "-a",
            help="Free-form agent label (shell / codex / claude / ...).",
        ),
    ] = "shell",
    detach: Annotated[
        bool,
        typer.Option(
            "--detach",
            "-d",
            help=(
                "Launch in a new session and return immediately. The run starts "
                "as status=running; use `run wait/status` to follow it."
            ),
        ),
    ] = False,
    actor: ActorOption = None,
) -> None:
    """Run a shell command and record it as a `run` node."""
    layout = ProjectLayout.require()

    if detach:
        try:
            started = start_run(
                layout,
                command=command,
                parent=parent,
                name=name,
                workdir=workdir,
                agent=agent,
                actor=resolve_actor(actor),
            )
        except RunnerError as exc:
            typer.echo(f"Runner error: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"Started (detached): {started.run_node_id}")
        typer.echo(f"  pid           = {started.pid}")
        typer.echo(f"  run_dir       = {started.run_dir}")
        typer.echo(f"  follow with   = simulanka run wait {started.run_node_id}")
        return

    try:
        result = exec_run(
            layout,
            command=command,
            parent=parent,
            name=name,
            workdir=workdir,
            timeout=timeout,
            agent=agent,
            actor=resolve_actor(actor),
        )
    except RunnerError as exc:
        typer.echo(f"Runner error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"Run recorded: {result.run_node_id}")
    typer.echo(f"  status        = {result.status}")
    typer.echo(f"  exit_code     = {result.exit_code}")
    typer.echo(f"  duration      = {result.duration_seconds:.2f}s")
    typer.echo(f"  run_dir       = {result.run_dir}")
    typer.echo(f"  stdout        = {result.stdout_path}")
    typer.echo(f"  stderr        = {result.stderr_path}")
    if result.status != "done":
        raise typer.Exit(code=1)


@run_app.command("agent")
def run_agent_cmd(
    agent: Annotated[
        str,
        typer.Option(
            "--agent",
            "-a",
            help=(
                "Agent name. Built-in: codex, claude. Override the argv via env var "
                "SIMULANKA_AGENT_<NAME>_ARGV='binary --flag {prompt}'."
            ),
        ),
    ],
    parent: Annotated[
        str,
        typer.Option(
            "--parent",
            "-p",
            help="Selector of the directory or experiment that owns this run.",
        ),
    ],
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Name for the run node (unique within parent)."),
    ],
    prompt: Annotated[
        str | None,
        typer.Option(
            "--prompt",
            help=(
                "Free-form goal text. Mutually exclusive with --task. "
                "No contract, no checks."
            ),
        ),
    ] = None,
    task: Annotated[
        str | None,
        typer.Option(
            "--task",
            help=(
                "Task node selector (id or /abs/path). Sources goal + budget + "
                "allowed_outputs + acceptance from that task; records a "
                "`fulfills` edge."
            ),
        ),
    ] = None,
    workdir: Annotated[
        Path | None,
        typer.Option(
            "--workdir",
            "-w",
            help="Agent working directory. Defaults to the project root.",
        ),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", "-t", help="Seconds before the agent is killed."),
    ] = None,
    extra: Annotated[
        list[str] | None,
        typer.Option(
            "--extra",
            help="Extra positional arg appended to the agent argv. Repeatable.",
        ),
    ] = None,
    track: Annotated[
        list[str] | None,
        typer.Option(
            "--track",
            help=(
                "Subdir (relative to workdir) to include in the workspace diff. "
                "Repeatable. Default: the entire workdir."
            ),
        ),
    ] = None,
    detach: Annotated[
        bool,
        typer.Option(
            "--detach",
            "-d",
            help=(
                "Launch in a new session and return immediately. The diff is "
                "computed lazily on the next `run status` / `run wait`. "
                "`--timeout` is ignored — use `run kill` to stop a detached run."
            ),
        ),
    ] = False,
    actor: ActorOption = None,
) -> None:
    """Invoke an agent CLI (codex / claude / ...) and capture what it touched."""
    layout = ProjectLayout.require()

    if (prompt is None) == (task is None):
        typer.echo(
            "Error: pass exactly one of --prompt or --task.", err=True,
        )
        raise typer.Exit(code=2)

    task_node_id: str | None = None
    if task is not None:
        try:
            task_node_id = resolve_node(layout, task).id
        except ValueError as exc:
            typer.echo(f"Error resolving --task: {exc}", err=True)
            raise typer.Exit(code=2) from exc

    if detach:
        try:
            started = start_agent_run(
                layout,
                agent=agent,
                prompt=prompt,
                task_node_id=task_node_id,
                parent=parent,
                name=name,
                workdir=workdir,
                extra_args=extra,
                track_scope=track,
                actor=resolve_actor(actor),
            )
        except (AgentError, RunnerError) as exc:
            typer.echo(f"Agent error: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"Started (detached, agent={agent}): {started.run_node_id}")
        typer.echo(f"  pid           = {started.pid}")
        typer.echo(f"  run_dir       = {started.run_dir}")
        typer.echo(f"  prompt        = {started.prompt_path}")
        if started.task_node_id is not None:
            typer.echo(f"  fulfills task = {started.task_node_id}")
        typer.echo(f"  follow with   = simulanka run wait {started.run_node_id}")
        return

    try:
        result = run_agent(
            layout,
            agent=agent,
            prompt=prompt,
            task_node_id=task_node_id,
            parent=parent,
            name=name,
            workdir=workdir,
            timeout=timeout,
            extra_args=extra,
            track_scope=track,
            actor=resolve_actor(actor),
        )
    except (AgentError, RunnerError) as exc:
        typer.echo(f"Agent error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"Run recorded: {result.run_node_id}")
    typer.echo(f"  agent         = {agent}")
    typer.echo(f"  status        = {result.status}")
    typer.echo(f"  exit_code     = {result.exit_code}")
    typer.echo(f"  duration      = {result.duration_seconds:.2f}s")
    typer.echo(f"  run_dir       = {result.run_dir}")
    typer.echo(f"  prompt        = {result.prompt_path}")
    typer.echo(f"  changes       = {result.changes_path}")
    typer.echo(
        f"  files: +{len(result.files_added)} "
        f"~{len(result.files_modified)} -{len(result.files_deleted)}"
    )
    if result.contract_check is not None:
        cc = result.contract_check
        typer.echo(f"  contract      = {cc.status}")
        if cc.out_of_scope_files:
            typer.echo(f"    out_of_scope = {cc.out_of_scope_files}")
        if cc.acceptance_exit_code is not None:
            typer.echo(f"    acceptance_exit = {cc.acceptance_exit_code}")
    if result.status != "done":
        raise typer.Exit(code=1)
    if result.contract_check is not None and result.contract_check.status != "passed":
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Execution bracket: begin / end
# ---------------------------------------------------------------------------

@run_app.command("begin")
def run_begin(
    task: Annotated[
        str,
        typer.Option(
            "--task",
            help="Task node selector (id or /abs/path) this run fulfills.",
        ),
    ],
    parent: Annotated[
        str | None,
        typer.Option(
            "--parent",
            "-p",
            help=(
                "Selector of the directory or experiment that owns this run. "
                "Defaults to the task's own parent."
            ),
        ),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Name for the run node (unique within parent)."),
    ] = None,
    workdir: Annotated[
        Path | None,
        typer.Option(
            "--workdir",
            "-w",
            help="Workspace to snapshot/diff. Defaults to the project root.",
        ),
    ] = None,
    actor: ActorOption = None,
) -> None:
    """Open an execution bracket: snapshot the workspace, mirror the contract, go."""
    layout = ProjectLayout.require()
    try:
        result = begin_run(
            layout,
            task=task,
            parent=parent,
            name=name,
            workdir=workdir,
            actor=resolve_actor(actor),
        )
    except (RunnerError, ValueError) as exc:
        typer.echo(f"Runner error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(result.run_node_id)
    typer.echo(f"  fulfills task  = {result.task_node_id}")
    typer.echo(f"  workdir        = {result.workdir}")
    typer.echo(f"  snapshot       = {result.snapshot_files} files")
    if result.git_head is not None:
        typer.echo(f"  git_head       = {result.git_head}")
        typer.echo(f"  baseline_dirty = {result.baseline_dirty}")
    typer.echo(f"  run_dir        = {result.run_dir}")
    typer.echo(f"  close with     = simulanka run end {result.run_node_id}")


@run_app.command("end")
def run_end(
    target: Annotated[
        str, typer.Argument(help="Run node selector (id or absolute path)."),
    ],
    status: Annotated[
        str,
        typer.Option("--status", help="Outcome claim: done or failed."),
    ] = "done",
    metrics: Annotated[
        Path | None,
        typer.Option(
            "--metrics",
            "-m",
            help=(
                "Metrics file (flat JSON scalar dict) to extract as evidence. "
                "Without it, <workdir>/metrics.json is extracted iff present."
            ),
        ),
    ] = None,
    actor: ActorOption = None,
) -> None:
    """Close a bracket: diff against the begin snapshot, run acceptance, seal the run."""
    layout = ProjectLayout.require()
    try:
        result = end_run(
            layout,
            run=target,
            status=status,
            metrics=metrics,
            actor=resolve_actor(actor),
        )
    except RunnerError as exc:
        typer.echo(f"Runner error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"Run ended: {result.run_node_id}")
    typer.echo(f"  status        = {result.status}")
    typer.echo(f"  duration      = {result.duration_seconds:.2f}s")
    typer.echo(f"  changes       = {result.changes_path}")
    typer.echo(
        f"  files: +{len(result.files_added)} "
        f"~{len(result.files_modified)} -{len(result.files_deleted)}"
    )
    if result.contract_check is not None:
        cc = result.contract_check
        typer.echo(f"  contract      = {cc.status}")
        if cc.out_of_scope_files:
            typer.echo(f"    out_of_scope = {cc.out_of_scope_files}")
        if cc.acceptance_exit_code is not None:
            typer.echo(f"    acceptance_exit = {cc.acceptance_exit_code}")
    if result.evidence_node_id is not None:
        marker = "" if result.evidence_created else " (already extracted)"
        typer.echo(f"  evidence      = {result.evidence_node_id}{marker}")
    if result.metrics_error is not None:
        typer.echo(f"  metrics       = REJECTED: {result.metrics_error}")
    if result.status != "done":
        raise typer.Exit(code=1)
    if result.contract_check is not None and result.contract_check.status != "passed":
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Detached-run management: status / wait / kill / reconcile
# ---------------------------------------------------------------------------

@run_app.command("status")
def run_status(
    target: Annotated[
        str, typer.Argument(help="Run node selector (id or absolute path)."),
    ],
    actor: ActorOption = None,
) -> None:
    """Reconcile and print the current state of a run."""
    layout = ProjectLayout.require()
    resolved_actor = resolve_actor(actor)
    node = _reconcile_or_die(layout, target, actor=resolved_actor)
    summary = finalize_agent_diff(layout, node, actor=resolved_actor)
    _print_run_summary(node, summary)
    if node.attrs.get("status") == "running":
        raise typer.Exit(code=2)
    if node.attrs.get("status") != "done":
        raise typer.Exit(code=1)


@run_app.command("wait")
def run_wait(
    target: Annotated[
        str, typer.Argument(help="Run node selector (id or absolute path)."),
    ],
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", "-t", help="Seconds to wait before giving up."),
    ] = None,
    interval: Annotated[
        float,
        typer.Option("--interval", "-i", help="Poll interval in seconds."),
    ] = 0.5,
    actor: ActorOption = None,
) -> None:
    """Block until the run finishes and print the final state."""
    layout = ProjectLayout.require()
    node_id = _resolve_to_id(layout, target)
    resolved_actor = resolve_actor(actor)
    try:
        node = wait_run(
            layout,
            node_id,
            timeout=timeout,
            poll_interval=interval,
            actor=resolved_actor,
        )
    except TimeoutError as exc:
        typer.echo(f"Timeout: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except RunnerError as exc:
        typer.echo(f"Runner error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    summary = finalize_agent_diff(layout, node, actor=resolved_actor)
    _print_run_summary(node, summary)
    if node.attrs.get("status") != "done":
        raise typer.Exit(code=1)


@run_app.command("kill")
def run_kill(
    target: Annotated[
        str, typer.Argument(help="Run node selector (id or absolute path)."),
    ],
) -> None:
    """Send SIGTERM to the run's process group. Subsequent status updates the graph."""
    layout = ProjectLayout.require()
    node_id = _resolve_to_id(layout, target)
    try:
        node = kill_run(layout, node_id)
    except RunnerError as exc:
        typer.echo(f"Runner error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Sent SIGTERM to run {node.id} (pid={node.attrs.get('pid')}).")
    typer.echo("Status will reflect the kill on the next `run status` / `run wait`.")


@run_app.command("reconcile")
def run_reconcile(
    target: Annotated[
        str | None,
        typer.Argument(
            help="Run selector. Use 'all' to reconcile every running run.",
        ),
    ] = None,
    actor: ActorOption = None,
) -> None:
    """Read on-disk markers and update graph state for one or all running runs."""
    layout = ProjectLayout.require()
    resolved_actor = resolve_actor(actor)
    if target is None or target == "all":
        running = [
            n for n in iter_nodes(layout)
            if n.type == "run" and n.attrs.get("status") == "running"
        ]
        if not running:
            typer.echo("No running runs.")
            return
        for n in running:
            updated = reconcile_run(layout, n.id, actor=resolved_actor)
            finalize_agent_diff(layout, updated, actor=resolved_actor)
            typer.echo(
                f"{updated.id}  {str(updated.attrs.get('status')):8s}  "
                f"exit={updated.attrs.get('exit_code')}  name={updated.name}"
            )
    else:
        node_id = _resolve_to_id(layout, target)
        node = reconcile_run(layout, node_id, actor=resolved_actor)
        summary = finalize_agent_diff(layout, node, actor=resolved_actor)
        _print_run_summary(node, summary)


def _resolve_to_id(layout: ProjectLayout, selector: str) -> str:
    try:
        return resolve_node(layout, selector).id
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _reconcile_or_die(
    layout: ProjectLayout,
    selector: str,
    *,
    actor: str,
) -> Node:
    node_id = _resolve_to_id(layout, selector)
    try:
        return reconcile_run(layout, node_id, actor=actor)
    except (RunNotFound, RunnerError) as exc:
        typer.echo(f"Runner error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _print_run_summary(
    node: Node, diff: AgentDiffSummary | None = None,
) -> None:
    payload: dict[str, object] = {
        "id": node.id,
        "name": node.name,
        "status": node.attrs.get("status"),
        "exit_code": node.attrs.get("exit_code"),
        "started_at": node.attrs.get("started_at"),
        "ended_at": node.attrs.get("ended_at"),
        "duration_seconds": node.attrs.get("duration_seconds"),
        "pid": node.attrs.get("pid"),
        "run_handle": node.attrs.get("run_handle"),
        "stdout_path": node.attrs.get("stdout_path"),
        "stderr_path": node.attrs.get("stderr_path"),
    }
    if diff is not None:
        payload["changes_path"] = diff.changes_path
        payload["files_added"] = len(diff.added)
        payload["files_modified"] = len(diff.modified)
        payload["files_deleted"] = len(diff.deleted)
        if diff.contract_check is not None:
            cc = diff.contract_check
            payload["contract_status"] = cc.status
            payload["out_of_scope_files"] = cc.out_of_scope_files
            payload["acceptance_exit_code"] = cc.acceptance_exit_code
    typer.echo(json.dumps(payload, indent=2))
