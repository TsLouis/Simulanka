from __future__ import annotations

from pathlib import Path

import typer

from simulanka import __version__
from simulanka.cli.export import export_app
from simulanka.cli.graph import graph_app
from simulanka.cli.import_ import import_app
from simulanka.cli.run import run_app
from simulanka.cli.serve import serve_app
from simulanka.cli.task import task_app
from simulanka.layout import init_project

app = typer.Typer(help="Simulanka — research graph kernel CLI", no_args_is_help=True)
app.add_typer(graph_app, name="graph")
app.add_typer(import_app, name="import")
app.add_typer(export_app, name="export")
app.add_typer(run_app, name="run")
app.add_typer(task_app, name="task")
app.add_typer(serve_app, name="serve")


@app.command()
def version() -> None:
    """Print kernel version."""
    typer.echo(__version__)


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
