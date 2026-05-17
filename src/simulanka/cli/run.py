"""``simulanka run`` — execute commands and record them as ``run`` nodes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from simulanka.agent import AgentError, run_agent
from simulanka.kernel.resolver import resolve_node
from simulanka.layout.project import ProjectLayout
from simulanka.runner import (
    RunnerError,
    RunNotFound,
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
    prompt: Annotated[
        str,
        typer.Option("--prompt", help="Task prompt to send to the agent."),
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
) -> None:
    """Invoke an agent CLI (codex / claude / ...) and capture what it touched."""
    layout = ProjectLayout.require()
    try:
        result = run_agent(
            layout,
            agent=agent,
            prompt=prompt,
            parent=parent,
            name=name,
            workdir=workdir,
            timeout=timeout,
            extra_args=extra,
            track_scope=track,
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
    if result.status != "done":
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Detached-run management: status / wait / kill / reconcile
# ---------------------------------------------------------------------------

@run_app.command("status")
def run_status(
    target: Annotated[
        str, typer.Argument(help="Run node selector (id or absolute path)."),
    ],
) -> None:
    """Reconcile and print the current state of a run."""
    layout = ProjectLayout.require()
    node = _reconcile_or_die(layout, target)
    _print_run_summary(node)
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
) -> None:
    """Block until the run finishes and print the final state."""
    layout = ProjectLayout.require()
    node_id = _resolve_to_id(layout, target)
    try:
        node = wait_run(layout, node_id, timeout=timeout, poll_interval=interval)
    except TimeoutError as exc:
        typer.echo(f"Timeout: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except RunnerError as exc:
        typer.echo(f"Runner error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    _print_run_summary(node)
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
) -> None:
    """Read on-disk markers and update graph state for one or all running runs."""
    layout = ProjectLayout.require()
    if target is None or target == "all":
        running = [
            n for n in iter_nodes(layout)
            if n.type == "run" and n.attrs.get("status") == "running"
        ]
        if not running:
            typer.echo("No running runs.")
            return
        for n in running:
            updated = reconcile_run(layout, n.id)
            typer.echo(
                f"{updated.id}  {str(updated.attrs.get('status')):8s}  "
                f"exit={updated.attrs.get('exit_code')}  name={updated.name}"
            )
    else:
        node_id = _resolve_to_id(layout, target)
        node = reconcile_run(layout, node_id)
        _print_run_summary(node)


def _resolve_to_id(layout: ProjectLayout, selector: str) -> str:
    try:
        return resolve_node(layout, selector).id
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _reconcile_or_die(layout: ProjectLayout, selector: str) -> Node:
    node_id = _resolve_to_id(layout, selector)
    try:
        return reconcile_run(layout, node_id)
    except (RunNotFound, RunnerError) as exc:
        typer.echo(f"Runner error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _print_run_summary(node: Node) -> None:
    typer.echo(json.dumps({
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
    }, indent=2))
