"""``simulanka import`` — bring external artifacts into the graph."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Annotated, Any

import typer

from simulanka.importer import ModelImportError, import_model
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
                "arguments and returns `(model, example_inputs_tuple)`."
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


def _load_callable(spec: str) -> Callable[[], tuple[Any, tuple[Any, ...]]]:
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
