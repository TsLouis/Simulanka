from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from simulanka import __version__
from simulanka.cli.actor import ActorOption, resolve_actor
from simulanka.cli.brief import brief_app
from simulanka.cli.evidence import evidence_app
from simulanka.cli.export import export_app
from simulanka.cli.graph import graph_app
from simulanka.cli.import_ import import_app
from simulanka.cli.note import note_app
from simulanka.cli.plan import plan_app
from simulanka.cli.run import run_app
from simulanka.cli.serve import serve_app
from simulanka.cli.task import task_app
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.propose import DEFAULT_MODEL, ProposeError, propose_edges

app = typer.Typer(help="Simulanka — research graph kernel CLI", no_args_is_help=True)
app.add_typer(graph_app, name="graph")
app.add_typer(import_app, name="import")
app.add_typer(export_app, name="export")
app.add_typer(run_app, name="run")
app.add_typer(task_app, name="task")
app.add_typer(plan_app, name="plan")
app.add_typer(brief_app, name="brief")
app.add_typer(evidence_app, name="evidence")
app.add_typer(note_app, name="note")
app.add_typer(serve_app, name="serve")


@app.command()
def version() -> None:
    """Print kernel version."""
    typer.echo(__version__)


@app.command("propose")
def propose_cmd(
    model_selector: Annotated[
        str,
        typer.Argument(help="Selector for the imported `model` node (id, /path, or name)."),
    ],
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="opencode provider/model to ask."),
    ] = DEFAULT_MODEL,
    actor: ActorOption = None,
) -> None:
    """§13.5.3: ask an agent to read a model's forward() and propose ghost edges.

    Lays down cited `data_flow` edges as `source=agent, status=proposed,
    verdict=unconfirmed` for the human to confirm. Uncited guesses are skipped.
    """
    layout = ProjectLayout.require()
    try:
        result = propose_edges(
            layout,
            model_selector,
            model=model,
            actor=resolve_actor(actor),
        )
    except ProposeError as exc:
        typer.echo(f"Propose failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Proposed {len(result.edge_ids)} ghost edge(s) on {result.model_node_id}:")
    for g in result.proposed:
        typer.echo(f"  {g.src} → {g.dst}    [{g.citation}]")
    if result.skipped:
        typer.echo(f"Skipped {len(result.skipped)}:", err=True)
        for g, reason in result.skipped:
            typer.echo(f"  {g.src} → {g.dst}: {reason}", err=True)
    typer.echo(f"graph_version={layout.load_manifest().graph_version}")


@app.command("init")
def init_cmd(
    path: Path = typer.Argument(Path("."), help="Project root (created if missing)."),
) -> None:
    """Initialize a Simulanka project at PATH."""
    result = init_project(path)
    if result.status == "created":
        typer.echo(f"Initialized Simulanka project at {result.layout.dot_dir}")
        typer.echo(f"  project_id      = {result.manifest.project_id}")
        typer.echo(f"  schema_version  = {result.manifest.schema_version}")
        typer.echo(f"  registry_version= {result.manifest.registry_version}")
    else:
        typer.echo(f"Already initialized at {result.layout.dot_dir}")
        typer.echo(f"  project_id    = {result.manifest.project_id}")
        typer.echo(f"  graph_version = {result.manifest.graph_version}")
