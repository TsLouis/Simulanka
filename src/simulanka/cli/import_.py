"""``simulanka import`` — bring external artifacts into the graph."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from simulanka.importer import (
    ManifestError,
    ModelImportError,
    check_baseline,
    import_baseline,
    import_model,
)
from simulanka.layout.project import ProjectLayout

import_app = typer.Typer(help="Import external artifacts into the graph.", no_args_is_help=True)


@import_app.command("torch")
def import_torch(
    build: Annotated[
        str,
        typer.Option(
            "--build",
            "-b",
            help=(
                "Build callable as `pkg.module:function`. The function takes no "
                "arguments and returns `(model, example_inputs)`. example_inputs "
                "may be `None` to skip the forward-pass data-flow trace and "
                "import the module hierarchy only."
            ),
        ),
    ],
    name: Annotated[
        str, typer.Option("--name", "-n", help="Name for the root `model` node."),
    ],
    parent: Annotated[
        str | None,
        typer.Option(
            "--parent",
            "-p",
            help="Directory selector to place the model under. Omit for project root.",
        ),
    ] = None,
) -> None:
    """Import a PyTorch model via ``torch.export``."""
    layout = ProjectLayout.require()
    try:
        build_fn = _load_callable(build)
    except (ImportError, AttributeError, ValueError) as exc:
        typer.echo(f"Error: cannot resolve --build {build!r}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    try:
        result = import_model(layout, build_fn, name=name, parent=parent)
    except ModelImportError as exc:
        typer.echo(f"Import failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Imported model: {result.model_node_id}")
    typer.echo(f"  modules:      {len(result.module_node_ids) - 1}")
    typer.echo(f"  data_flow:    {len(result.data_flow_edge_ids)} edge(s)")
    typer.echo(f"  graph_version={layout.load_manifest().graph_version}")


@import_app.command("baseline")
def import_baseline_cmd(
    baseline_dir: Annotated[
        Path,
        typer.Argument(
            help=(
                "Baseline directory containing `simulanka_builds/manifest.yaml`. "
                "Top-level model is committed structure-only; each child entry "
                "in the manifest is committed as a sibling `model` node under "
                "`--parent` with a focused dataflow trace."
            ),
        ),
    ],
    parent: Annotated[
        str | None,
        typer.Option(
            "--parent",
            "-p",
            help="Directory selector to place the imported nodes under. Omit for project root.",
        ),
    ] = None,
    check_only: Annotated[
        bool,
        typer.Option(
            "--check",
            help=(
                "Lint only: instantiate the top-level and verify children "
                "coverage. Does not mutate the graph."
            ),
        ),
    ] = False,
) -> None:
    """Import a baseline declaratively from its ``simulanka_builds/manifest.yaml``."""
    manifest_path = baseline_dir / "simulanka_builds" / "manifest.yaml"

    if check_only:
        try:
            issues = check_baseline(manifest_path)
        except ManifestError as exc:
            typer.echo(f"Lint failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        if issues:
            typer.echo(f"Lint found {len(issues)} issue(s):", err=True)
            for issue in issues:
                typer.echo(f"  [{issue.severity}] {issue.message}", err=True)
            raise typer.Exit(code=1)
        typer.echo("Lint passed: manifest covers every direct child of the top-level model.")
        return

    layout = ProjectLayout.require()
    try:
        summary = import_baseline(layout, manifest_path, parent=parent)
    except ManifestError as exc:
        typer.echo(f"Import failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Imported baseline (top-level: {summary.top_level_name})")
    typer.echo(f"  top-level node:      {summary.top_level_node_id}")
    typer.echo(f"  focused traces:      {len(summary.child_node_ids)}")
    for fqn, node_id in summary.child_node_ids.items():
        typer.echo(f"    {fqn}: {node_id}")
    if summary.skipped:
        typer.echo(f"  skipped (waived):    {summary.skipped}")
    typer.echo(f"  graph_version=       {layout.load_manifest().graph_version}")


def _load_callable(spec: str) -> Callable[[], tuple[Any, tuple[Any, ...] | None]]:
    """Resolve ``pkg.module:function`` to the callable."""
    if ":" not in spec:
        raise ValueError(
            "expected `pkg.module:function`; got no ':' separator."
        )
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError("module and attribute names must both be non-empty.")
    module = importlib.import_module(module_name)
    fn = getattr(module, attr)
    if not callable(fn):
        raise ValueError(f"{spec!r} is not callable.")
    return fn  # type: ignore[no-any-return]
