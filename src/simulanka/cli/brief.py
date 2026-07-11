"""``simulanka brief`` — deterministic graph → analyst opening document."""

from __future__ import annotations

from typing import Annotated

import typer

from simulanka.brief import export_brief
from simulanka.layout.file_registry import FileRegistryError
from simulanka.layout.project import ProjectLayout

brief_app = typer.Typer(
    help="Export the analyst's opening brief from the graph.", no_args_is_help=True,
)


@brief_app.command("export")
def brief_export(
    out: Annotated[
        str | None,
        typer.Option(
            "--out",
            "-o",
            help=(
                "Brief name — FileRegistry places it at research/brief-<name>.md "
                "and registers it. Without --out the markdown goes to stdout."
            ),
        ),
    ] = None,
) -> None:
    """Render the brief (open atoms, recent runs + evidence ids, escalations)."""
    layout = ProjectLayout.require()
    try:
        result = export_brief(layout, out=out)
    except FileRegistryError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if result.relative_path is None:
        typer.echo(result.markdown)
    else:
        typer.echo(f"Brief written: {result.relative_path}")
        typer.echo(f"  file node = {result.file_node_id}")
