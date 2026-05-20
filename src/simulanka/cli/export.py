"""``simulanka export`` — emit a graph view in a third-party format."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from simulanka.exporter import to_model_explorer
from simulanka.kernel.resolver import ResolveError
from simulanka.layout.project import ProjectLayout

export_app = typer.Typer(
    help="Export a graph view in a third-party format.", no_args_is_help=True,
)


@export_app.command("model-explorer")
def export_model_explorer(
    selector: Annotated[
        str,
        typer.Argument(
            help=(
                "Selector for the model node to export. Accepts a stable "
                "`nod_...` id or an absolute path `/a/b/SAM2VP`."
            ),
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write JSON to this path. Omit to print to stdout.",
        ),
    ] = None,
) -> None:
    """Export a model node + its data-flow subgraph as Model Explorer JSON.

    Open the resulting file at https://model-explorer.googleapis.com (or with
    the local ``model-explorer`` CLI) to browse / collapse / search the
    architecture interactively.
    """
    layout = ProjectLayout.require()
    try:
        payload = to_model_explorer(layout, selector)
    except ResolveError as exc:
        typer.echo(f"Cannot resolve {selector!r}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"Export failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    payload_json = json.dumps(payload, indent=2)
    if output is None:
        typer.echo(payload_json)
        return
    output.write_text(payload_json)
    n_nodes = len(payload["graphs"][0]["nodes"])
    typer.echo(f"Wrote Model Explorer JSON to {output} ({n_nodes} nodes).")
