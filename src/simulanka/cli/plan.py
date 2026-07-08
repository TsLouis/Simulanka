"""``simulanka plan`` — analyst plan files (§14.7): deterministic ingest."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from simulanka.layout.project import ProjectLayout
from simulanka.plan import PlanError, ingest_plan

plan_app = typer.Typer(
    help="Analyst plan files (§14.7): land the fenced block on the graph.",
    no_args_is_help=True,
)


@plan_app.command("ingest")
def plan_ingest_cmd(
    file: Annotated[
        Path,
        typer.Argument(help="Markdown file with exactly one ```simulanka-plan block."),
    ],
) -> None:
    """Parse FILE and land its plan block as one atomic patch (all-or-nothing)."""
    layout = ProjectLayout.require()
    try:
        result = ingest_plan(layout, file)
    except PlanError as exc:
        typer.echo(f"Plan rejected: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    receipt = result.receipt
    typer.echo(f"Ingested plan {result.relative_path}")
    typer.echo(f"  file_node     = {result.file_node_id}")
    typer.echo(f"  plan_dir      = {result.plan_dir_id}")
    typer.echo(f"  nodes_created = {len(receipt.nodes)}")
    typer.echo(f"  edges_created = {len(receipt.edges)}")
    typer.echo(f"  nodes_updated = {len(receipt.updated_nodes)}")
    typer.echo(f"  graph_version = {receipt.graph_version}")
    if result.escalate_reason is not None:
        # Operator contract (§14.4): seeing this line means stop the round.
        typer.echo(f"ESCALATE: {result.escalate_reason}")
