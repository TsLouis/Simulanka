"""``simulanka note`` — human acts on note nodes (escalate closure)."""

from __future__ import annotations

from typing import Annotated

import typer

from simulanka.cli.actor import ActorOption, resolve_actor
from simulanka.layout.project import ProjectLayout
from simulanka.plan import PlanError, resolve_escalate

note_app = typer.Typer(help="Act on note nodes.", no_args_is_help=True)


@note_app.command("resolve")
def note_resolve(
    target: Annotated[
        str, typer.Argument(help="Escalate note selector (id or absolute path)."),
    ],
    note: Annotated[
        str | None,
        typer.Option("--note", help="Optional disposition reason (resolve_note)."),
    ] = None,
    actor: ActorOption = None,
) -> None:
    """Mark an escalate note as resolved — the explicit human act that clears
    a stop signal (nothing else can; a later plan ingest never auto-mutes it)."""
    layout = ProjectLayout.require()
    try:
        node = resolve_escalate(
            layout,
            target,
            resolve_note=note,
            actor=resolve_actor(actor),
        )
    except PlanError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Resolved: {node.id}")
    typer.echo(f"  body = {node.attrs.get('body')}")
    if note is not None:
        typer.echo(f"  resolve_note = {note}")
