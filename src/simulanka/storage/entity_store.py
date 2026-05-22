from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Edge, Node, Port


def node_path(layout: ProjectLayout, node_id: str) -> Path:
    return layout.nodes_dir / f"{node_id}.json"


def edge_path(layout: ProjectLayout, edge_id: str) -> Path:
    return layout.edges_dir / f"{edge_id}.json"


def port_path(layout: ProjectLayout, port_id: str) -> Path:
    return layout.ports_dir / f"{port_id}.json"


def save_node(layout: ProjectLayout, node: Node) -> None:
    _atomic_write_json(node_path(layout, node.id), json.loads(node.model_dump_json()))


def save_edge(layout: ProjectLayout, edge: Edge) -> None:
    _atomic_write_json(edge_path(layout, edge.id), json.loads(edge.model_dump_json()))


def save_port(layout: ProjectLayout, port: Port) -> None:
    _atomic_write_json(port_path(layout, port.id), json.loads(port.model_dump_json()))


def load_node(layout: ProjectLayout, node_id: str) -> Node:
    return Node.model_validate_json(node_path(layout, node_id).read_text("utf-8"))


def load_edge(layout: ProjectLayout, edge_id: str) -> Edge:
    return Edge.model_validate_json(edge_path(layout, edge_id).read_text("utf-8"))


def load_port(layout: ProjectLayout, port_id: str) -> Port:
    return Port.model_validate_json(port_path(layout, port_id).read_text("utf-8"))


def delete_edge(layout: ProjectLayout, edge_id: str) -> None:
    edge_path(layout, edge_id).unlink(missing_ok=True)


def node_exists(layout: ProjectLayout, node_id: str) -> bool:
    return node_path(layout, node_id).is_file()


def edge_exists(layout: ProjectLayout, edge_id: str) -> bool:
    return edge_path(layout, edge_id).is_file()


def port_exists(layout: ProjectLayout, port_id: str) -> bool:
    return port_path(layout, port_id).is_file()


def iter_nodes(layout: ProjectLayout) -> Iterator[Node]:
    for path in _entity_files(layout.nodes_dir):
        yield Node.model_validate_json(path.read_text("utf-8"))


def iter_edges(layout: ProjectLayout) -> Iterator[Edge]:
    for path in _entity_files(layout.edges_dir):
        yield Edge.model_validate_json(path.read_text("utf-8"))


def iter_ports(layout: ProjectLayout) -> Iterator[Port]:
    for path in _entity_files(layout.ports_dir):
        yield Port.model_validate_json(path.read_text("utf-8"))


def list_ports_of(layout: ProjectLayout, node_id: str) -> list[Port]:
    return [p for p in iter_ports(layout) if p.node_id == node_id]


def find_port(layout: ProjectLayout, node_id: str, name: str) -> Port | None:
    for p in iter_ports(layout):
        if p.node_id == node_id and p.name == name:
            return p
    return None


def _entity_files(directory: Path) -> Iterator[Path]:
    if not directory.is_dir():
        return
    for entry in sorted(directory.iterdir()):
        if entry.is_file() and entry.suffix == ".json":
            yield entry


def _atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
