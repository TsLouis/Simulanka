from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from simulanka.kernel.events import Event, append_event, iter_events
from simulanka.kernel.manifest import Manifest, compute_content_hash, load_manifest, write_manifest
from simulanka.layout.project import DIR_NAME, GITIGNORE_BODY, ProjectLayout
from simulanka.schema.entities import Edge, Node, Port
from simulanka.storage.entity_store import (
    iter_edges,
    iter_nodes,
    iter_ports,
    save_edge,
    save_node,
    save_port,
)
from simulanka.storage.write_lock import project_write_lock

BUNDLE_FORMAT: Literal["simulanka.bundle.v1"] = "simulanka.bundle.v1"


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["simulanka.bundle.v1"] = BUNDLE_FORMAT
    manifest: Manifest
    nodes: list[Node]
    edges: list[Edge]
    ports: list[Port]
    events: list[Event]


def export_bundle(layout: ProjectLayout) -> Bundle:
    return Bundle(
        manifest=load_manifest(layout),
        nodes=list(iter_nodes(layout)),
        edges=list(iter_edges(layout)),
        ports=list(iter_ports(layout)),
        events=list(iter_events(layout)),
    )


def write_bundle(bundle: Bundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(bundle.model_dump_json())
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_bundle(path: Path) -> Bundle:
    return Bundle.model_validate_json(path.read_text("utf-8"))


class ImportTargetNotEmpty(RuntimeError):
    """Target already contains a Simulanka project."""


def import_bundle(bundle: Bundle, target_root: Path) -> ProjectLayout:
    """Materialize a bundle into a fresh project rooted at *target_root*.

    Refuses to overwrite an existing `.simulanka/` directory.
    """
    target_root = target_root.resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    layout = ProjectLayout(target_root)
    with project_write_lock(layout.root):
        if layout.dot_dir.exists():
            raise ImportTargetNotEmpty(
                f"Target `{layout.dot_dir}` already exists. "
                "Choose a fresh path or remove it first."
            )

        for d in (
            layout.dot_dir,
            layout.graph_dir,
            layout.nodes_dir,
            layout.edges_dir,
            layout.ports_dir,
            layout.events_dir,
            layout.indexes_dir,
            layout.logs_dir,
            layout.cache_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        for node in bundle.nodes:
            save_node(layout, node)
        for port in bundle.ports:
            save_port(layout, port)
        for edge in bundle.edges:
            save_edge(layout, edge)
        for event in bundle.events:
            append_event(layout, event)

        # Re-derive content_hash from disk so any benign reformat is corrected,
        # and persist the manifest.
        materialized = bundle.manifest.model_copy(
            update={"content_hash": compute_content_hash(layout)}
        )
        write_manifest(layout, materialized)

        (layout.dot_dir / ".gitignore").write_text(GITIGNORE_BODY, encoding="utf-8")
        return layout


__all__ = [
    "BUNDLE_FORMAT",
    "Bundle",
    "ImportTargetNotEmpty",
    "DIR_NAME",
    "export_bundle",
    "import_bundle",
    "read_bundle",
    "write_bundle",
]
