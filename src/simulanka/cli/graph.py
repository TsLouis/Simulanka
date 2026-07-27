from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from simulanka.cli.actor import ActorOption, resolve_actor
from simulanka.kernel.apply import VersionConflict, apply_patch
from simulanka.kernel.bundle import (
    ImportTargetNotEmpty,
    export_bundle,
    import_bundle,
    read_bundle,
    write_bundle,
)
from simulanka.kernel.doctor import repair, run_doctor
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp, CreatePortOp, PatchIntent
from simulanka.kernel.migration import (
    MigrationError,
    SchemaMismatch,
    plan_migrations,
    run_migrations,
)
from simulanka.kernel.resolver import ResolveError, resolve_node
from simulanka.kernel.validator import ValidationError
from simulanka.layout.file_registry import FileRegistryError, create_file, register_file
from simulanka.layout.project import ProjectLayout
from simulanka.registry.types import PortDirection
from simulanka.storage.entity_store import iter_nodes, list_ports_of
from simulanka.storage.index import rebuild_index

graph_app = typer.Typer(help="Inspect and mutate the graph.", no_args_is_help=True)
node_app = typer.Typer(help="Node operations.", no_args_is_help=True)
port_app = typer.Typer(help="Port operations.", no_args_is_help=True)
file_app = typer.Typer(help="File operations (governed by FileRegistry).", no_args_is_help=True)
index_app = typer.Typer(help="SQLite index operations.", no_args_is_help=True)
graph_app.add_typer(node_app, name="node")
graph_app.add_typer(port_app, name="port")
graph_app.add_typer(file_app, name="file")
graph_app.add_typer(index_app, name="index")


@node_app.command("create")
def node_create(
    type_: Annotated[str, typer.Option("--type", "-t", help="Node type.")],
    name: Annotated[str, typer.Option("--name", "-n", help="Node name within parent scope.")],
    parent: Annotated[
        str | None,
        typer.Option("--parent", "-p", help="Parent selector (id or /abs/path). Omit for root."),
    ] = None,
    attr: Annotated[
        list[str] | None,
        typer.Option(
            "--attr",
            "-a",
            help="Attribute as key=value. JSON-decoded when possible. Repeatable.",
        ),
    ] = None,
    note: Annotated[str | None, typer.Option("--note", help="Patch note.")] = None,
    actor: ActorOption = None,
) -> None:
    """Create a node."""
    layout = ProjectLayout.require()
    intent = PatchIntent(
        ops=[CreateNodeOp(type=type_, name=name, parent=parent, attrs=_parse_attrs(attr or []))],
        actor=resolve_actor(actor),
        base_graph_version=layout.load_manifest().graph_version,
        note=note,
    )
    receipt = _commit(intent, layout)
    [node_id] = receipt.nodes
    typer.echo(f"Created {node_id}")
    if receipt.edges:
        typer.echo(f"  contains edge: {receipt.edges[0]}")
    typer.echo(f"  graph_version = {receipt.graph_version}")
    typer.echo(f"  event_id      = {receipt.event_id}")


@node_app.command("inspect")
def node_inspect(
    selector: Annotated[str, typer.Argument(help="Node id or absolute path.")],
    show_children: Annotated[
        bool, typer.Option("--children/--no-children", help="List immediate children.")
    ] = True,
    show_ports: Annotated[
        bool, typer.Option("--ports/--no-ports", help="List the node's ports.")
    ] = True,
) -> None:
    """Show a node's fields, ports, and immediate children."""
    layout = ProjectLayout.require()
    try:
        node = resolve_node(layout, selector)
    except ResolveError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(json.dumps(json.loads(node.model_dump_json()), indent=2, sort_keys=True))

    if show_ports:
        ports = list_ports_of(layout, node.id)
        if ports:
            typer.echo("\nports:")
            for port in ports:
                typer.echo(f"  {port.id}  {port.direction:<3} {port.name} ({port.port_type})")

    if show_children:
        children = [n for n in iter_nodes(layout) if n.parent_id == node.id]
        if children:
            typer.echo("\nchildren:")
            for child in children:
                typer.echo(f"  {child.id}  {child.type:<12} {child.name}")


@port_app.command("create")
def port_create(
    node: Annotated[str, typer.Argument(help="Node selector to attach the port to.")],
    name: Annotated[str, typer.Option("--name", "-n", help="Port name (unique per node).")],
    direction: Annotated[PortDirection, typer.Option("--direction", "-d", help="in|out")],
    port_type: Annotated[
        str, typer.Option("--type", "-t", help="Port type (e.g. tensor, scalar, any).")
    ] = "any",
    attr: Annotated[
        list[str] | None,
        typer.Option("--attr", "-a", help="Attribute as key=value. Repeatable."),
    ] = None,
    actor: ActorOption = None,
) -> None:
    """Create a port on a node."""
    layout = ProjectLayout.require()
    intent = PatchIntent(
        ops=[
            CreatePortOp(
                node=node, name=name, direction=direction,
                port_type=port_type, attrs=_parse_attrs(attr or []),
            )
        ],
        actor=resolve_actor(actor),
        base_graph_version=layout.load_manifest().graph_version,
    )
    receipt = _commit(intent, layout)
    [port_id] = receipt.ports
    typer.echo(f"Created {port_id}")
    typer.echo(f"  graph_version = {receipt.graph_version}")


@graph_app.command("connect")
def connect(
    source: Annotated[str, typer.Argument(help="Source selector (port for data_flow).")],
    target: Annotated[str, typer.Argument(help="Target selector (port for data_flow).")],
    type_: Annotated[
        str, typer.Option("--type", "-t", help="Edge type (e.g. data_flow).")
    ] = "data_flow",
    attr: Annotated[
        list[str] | None,
        typer.Option("--attr", "-a", help="Attribute as key=value. Repeatable."),
    ] = None,
    actor: ActorOption = None,
) -> None:
    """Create an edge between two endpoints."""
    layout = ProjectLayout.require()
    intent = PatchIntent(
        ops=[
            CreateEdgeOp(
                type=type_, source=source, target=target, attrs=_parse_attrs(attr or []),
            )
        ],
        actor=resolve_actor(actor),
        base_graph_version=layout.load_manifest().graph_version,
    )
    receipt = _commit(intent, layout)
    [edge_id] = receipt.edges
    typer.echo(f"Created {edge_id}")
    typer.echo(f"  graph_version = {receipt.graph_version}")


@graph_app.command("export")
def export_cmd(
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Path to write the bundle to. Default: stdout."),
    ] = None,
) -> None:
    """Export the project as a single JSON bundle."""
    layout = ProjectLayout.require()
    bundle = export_bundle(layout)
    if out is None:
        typer.echo(bundle.model_dump_json(indent=2))
    else:
        write_bundle(bundle, out)
        typer.echo(f"Wrote {out}")


@graph_app.command("import")
def import_cmd(
    file: Annotated[Path, typer.Option("--file", "-f", help="Bundle JSON to import.")],
    target: Annotated[
        Path,
        typer.Argument(help="Target project root. Must not already contain `.simulanka/`."),
    ],
) -> None:
    """Initialize a project from an exported bundle."""
    try:
        bundle = read_bundle(file)
        layout = import_bundle(bundle, target)
    except ImportTargetNotEmpty as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Imported {len(bundle.nodes)} nodes, {len(bundle.edges)} edges, "
               f"{len(bundle.ports)} ports into {layout.dot_dir}")


@file_app.command("create")
def file_create_cmd(
    kind: Annotated[
        str,
        typer.Option("--kind", "-k", help="File kind: code | test | doc | paper | artifact."),
    ],
    name: Annotated[str, typer.Option("--name", "-n", help="File name (extension auto-applied).")],
    content_file: Annotated[
        Path | None,
        typer.Option(
            "--content-file",
            help="Path to seed content. If omitted, an empty file is created.",
        ),
    ] = None,
    actor: ActorOption = None,
) -> None:
    """Create a new managed file at the kind-determined path and register it."""
    layout = ProjectLayout.require()
    content = content_file.read_bytes() if content_file is not None else b""
    try:
        result = create_file(layout, kind, name, content, actor=resolve_actor(actor))
    except (FileRegistryError, ValidationError, ResolveError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Created {result.node_id}")
    typer.echo(f"  path = {result.relative_path}")
    typer.echo(f"  kind = {result.kind}")


@file_app.command("register")
def file_register_cmd(
    path: Annotated[Path, typer.Argument(help="Path relative to project root.")],
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            "-k",
            help="File kind: code | test | doc | paper | baseline | artifact.",
        ),
    ],
    actor: ActorOption = None,
) -> None:
    """Register an existing file (or reference directory) into the graph."""
    layout = ProjectLayout.require()
    try:
        result = register_file(layout, kind, path, actor=resolve_actor(actor))
    except (FileRegistryError, ValidationError, ResolveError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Registered {result.node_id}")
    typer.echo(f"  path = {result.relative_path}")
    typer.echo(f"  kind = {result.kind}")


@graph_app.command("migrate")
def migrate_cmd(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the migration plan without applying.")
    ] = False,
    actor: ActorOption = None,
) -> None:
    """Bring the project's schema/registry versions up to the code's current versions."""
    layout = ProjectLayout.require()
    try:
        plan = plan_migrations(layout)
    except MigrationError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(
        f"schema: v{plan.current_schema} → v{plan.target_schema} | "
        f"registry: v{plan.current_registry} → v{plan.target_registry}"
    )
    if plan.is_empty:
        typer.echo("Nothing to migrate.")
        return
    for step in plan.steps:
        typer.echo(f"  - {step.kind} {step.name}: v{step.from_version} → v{step.to_version}")

    if dry_run:
        typer.echo("\n(dry-run; no changes written.)")
        return
    run_migrations(layout, actor=resolve_actor(actor))
    typer.echo("\nMigration applied.")


@index_app.command("rebuild")
def index_rebuild() -> None:
    """Rebuild the SQLite query index from entity files."""
    layout = ProjectLayout.require()
    rebuild_index(layout)
    typer.echo(f"Rebuilt index at {layout.indexes_dir / 'graph.sqlite'}")


@graph_app.command("doctor")
def doctor_cmd(
    repair_flag: Annotated[
        bool,
        typer.Option("--repair", help="Auto-fix derived state (currently: SQLite index drift)."),
    ] = False,
) -> None:
    """Check graph invariants. With --repair, fix derived state only."""
    layout = ProjectLayout.require()
    report = run_doctor(layout)
    if report.ok:
        typer.echo("doctor: ok (no issues)")
        return
    for issue in report.issues:
        flag = " [auto-fixable]" if issue.auto_fixable else ""
        typer.echo(f"  [{issue.severity}] {issue.code}: {issue.message}{flag}")
    if repair_flag:
        result = repair(layout, report)
        typer.echo(
            f"\nrepair: fixed {len(result.repaired)} ({', '.join(result.repaired) or '-'}), "
            f"skipped {len(result.skipped)} ({', '.join(result.skipped) or '-'})"
        )
        # Re-run to show remaining issues
        post = run_doctor(layout)
        if post.ok:
            typer.echo("doctor: ok after repair")
        else:
            typer.echo(f"doctor: {len(post.issues)} issue(s) remain.")
            raise typer.Exit(code=1)
    else:
        # Non-zero exit so CI can wire it up
        raise typer.Exit(code=1)


def _commit(intent: PatchIntent, layout: ProjectLayout) -> Any:
    try:
        return apply_patch(layout, intent)
    except (
        ResolveError,
        ValidationError,
        VersionConflict,
        SchemaMismatch,
        ValueError,
    ) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _parse_attrs(items: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in items:
        if "=" not in raw:
            raise typer.BadParameter(f"--attr `{raw}` must be key=value.")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter(f"--attr `{raw}` has empty key.")
        try:
            out[key] = json.loads(value)
        except json.JSONDecodeError:
            out[key] = value
    return out
