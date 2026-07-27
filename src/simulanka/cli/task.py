"""``simulanka task`` — create and inspect ``task`` nodes (agent contracts)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError as PydanticValidationError

from simulanka.cli.actor import ActorOption, resolve_actor
from simulanka.contract import (
    AcceptanceSpec,
    BudgetSpec,
    TaskContract,
    contract_from_task_attrs,
    task_node_attrs,
)
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.kernel.resolver import ResolveError, resolve_node
from simulanka.layout.project import ProjectLayout
from simulanka.storage.entity_store import iter_edges, load_node

task_app = typer.Typer(
    help="Create and inspect task contracts (agent attempts will `fulfills` them).",
    no_args_is_help=True,
)


@task_app.command("create")
def task_create(
    parent: Annotated[
        str,
        typer.Option("--parent", "-p", help="Directory or experiment selector."),
    ],
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Task name (unique within parent)."),
    ],
    contract_file: Annotated[
        Path | None,
        typer.Option(
            "--contract",
            "-c",
            help="Path to a JSON file containing a full TaskContract. "
            "Mutually exclusive with the inline --goal/--allow/... flags.",
        ),
    ] = None,
    goal: Annotated[
        str | None,
        typer.Option("--goal", help="What the agent should accomplish."),
    ] = None,
    allow: Annotated[
        list[str] | None,
        typer.Option(
            "--allow",
            help=(
                "Glob the agent may add/modify/delete (gitignore-ish, ** supported). "
                "Repeatable. Default: no restriction."
            ),
        ),
    ] = None,
    budget_time: Annotated[
        float | None,
        typer.Option(
            "--budget-time", help="Wall-clock budget in seconds (sync runs only).",
        ),
    ] = None,
    accept: Annotated[
        str | None,
        typer.Option(
            "--accept",
            help="Shell command run in workdir after the agent; exit 0 = passed.",
        ),
    ] = None,
    actor: ActorOption = None,
) -> None:
    """Create a task node from inline flags or a JSON contract file."""
    layout = ProjectLayout.require()

    inline_given = any(v is not None for v in (goal, allow, budget_time, accept))
    if contract_file is not None and inline_given:
        typer.echo(
            "Error: --contract is mutually exclusive with inline flags "
            "(--goal/--allow/--budget-time/--accept).",
            err=True,
        )
        raise typer.Exit(code=2)

    if contract_file is not None:
        try:
            data = json.loads(contract_file.read_text(encoding="utf-8"))
            contract = TaskContract.model_validate(data)
        except (OSError, json.JSONDecodeError, PydanticValidationError) as exc:
            typer.echo(f"Error reading contract: {exc}", err=True)
            raise typer.Exit(code=2) from exc
    else:
        if not goal:
            typer.echo(
                "Error: --goal is required (or pass --contract <file>).", err=True,
            )
            raise typer.Exit(code=2)
        contract = TaskContract(
            goal=goal,
            allowed_outputs=allow or [],
            budget=BudgetSpec(time_seconds=budget_time),
            acceptance=AcceptanceSpec(command=accept) if accept else None,
        )

    intent = PatchIntent(
        ops=[
            CreateNodeOp(
                type="task", name=name, parent=parent, attrs=task_node_attrs(contract),
            ),
        ],
        actor=resolve_actor(actor),
        base_graph_version=layout.load_manifest().graph_version,
        note=f"task create {name}",
    )
    receipt = apply_patch(layout, intent)
    [task_id] = receipt.nodes
    typer.echo(f"Created task {task_id}  name={name}")
    typer.echo(f"  goal              = {contract.goal}")
    if contract.allowed_outputs:
        typer.echo(f"  allowed_outputs   = {contract.allowed_outputs}")
    if contract.budget.time_seconds is not None:
        typer.echo(f"  budget_time_secs  = {contract.budget.time_seconds}")
    if contract.acceptance is not None:
        typer.echo(f"  acceptance        = {contract.acceptance.command}")
    typer.echo(f"  graph_version     = {receipt.graph_version}")


@task_app.command("inspect")
def task_inspect(
    target: Annotated[
        str, typer.Argument(help="Task node selector (id or /abs/path)."),
    ],
) -> None:
    """Print the task contract and all runs that fulfill it."""
    layout = ProjectLayout.require()
    try:
        node = resolve_node(layout, target)
    except ResolveError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if node.type != "task":
        typer.echo(
            f"Error: node {node.id} is type {node.type!r}, not 'task'.", err=True,
        )
        raise typer.Exit(code=2)

    contract = contract_from_task_attrs(node.attrs)

    fulfilling_runs: list[dict[str, object]] = []
    for edge in iter_edges(layout):
        if edge.type == "fulfills" and edge.target_id == node.id:
            run = load_node(layout, edge.source_id)
            check = run.attrs.get("contract_check") or {}
            fulfilling_runs.append(
                {
                    "id": run.id,
                    "name": run.name,
                    "status": run.attrs.get("status"),
                    "exit_code": run.attrs.get("exit_code"),
                    "contract_status": (
                        check.get("status") if isinstance(check, dict) else None
                    ),
                },
            )

    payload = {
        "id": node.id,
        "name": node.name,
        "parent_id": node.parent_id,
        "contract": contract.model_dump(),
        "runs": fulfilling_runs,
    }
    typer.echo(json.dumps(payload, indent=2))
