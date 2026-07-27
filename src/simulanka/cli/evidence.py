"""``simulanka evidence`` — deterministic metrics → evidence extraction.

Exit codes: ``0`` success (including the idempotent no-op), ``1`` the metrics
file exists but is invalid (rejection recorded on the run node), ``2`` usage
error (bad selector, file not found).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from simulanka.cli.actor import ActorOption, resolve_actor
from simulanka.evidence import EvidenceError, MetricsError, extract_evidence
from simulanka.layout.project import ProjectLayout

evidence_app = typer.Typer(
    help="Extract measured metrics into evidence nodes.", no_args_is_help=True,
)


@evidence_app.command("extract")
def evidence_extract(
    target: Annotated[
        str, typer.Argument(help="Run node selector (id or absolute path)."),
    ],
    metrics: Annotated[
        Path | None,
        typer.Option(
            "--metrics",
            "-m",
            help="Metrics file (flat JSON scalar dict). Defaults to <workdir>/metrics.json.",
        ),
    ] = None,
    actor: ActorOption = None,
) -> None:
    """Extract a run's metrics file into an `evidence` node (idempotent)."""
    layout = ProjectLayout.require()
    try:
        result = extract_evidence(
            layout,
            run=target,
            metrics=metrics,
            actor=resolve_actor(actor),
        )
    except MetricsError as exc:
        typer.echo(f"Rejected: {exc}", err=True)
        typer.echo("(recorded as `metrics_error` on the run node)", err=True)
        raise typer.Exit(code=1) from exc
    except EvidenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    verb = "Evidence recorded" if result.created else "Already extracted (no-op)"
    typer.echo(f"{verb}: {result.evidence_node_id}")
    typer.echo(f"  metrics_path  = {result.metrics_path}")
    for key in sorted(result.metrics):
        typer.echo(f"  {key} = {result.metrics[key]}")
