from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from simulanka.layout.project import ProjectLayout
from simulanka.storage.entity_store import iter_edges, iter_nodes, iter_ports

SCHEMA = """
CREATE TABLE node (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX node_parent ON node(parent_id);
CREATE INDEX node_type   ON node(type);

CREATE TABLE edge (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    source_port_id TEXT,
    target_port_id TEXT
);
CREATE INDEX edge_source ON edge(source_id);
CREATE INDEX edge_target ON edge(target_id);
CREATE INDEX edge_type   ON edge(type);

CREATE TABLE port (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    name TEXT NOT NULL,
    direction TEXT NOT NULL,
    port_type TEXT NOT NULL
);
CREATE INDEX port_node ON port(node_id);
"""


def index_path(layout: ProjectLayout) -> Path:
    return layout.indexes_dir / "graph.sqlite"


def rebuild_index(layout: ProjectLayout) -> None:
    """Drop the SQLite index and rebuild it from entity files on disk."""
    target = index_path(layout)
    if target.exists():
        target.unlink()
    layout.indexes_dir.mkdir(parents=True, exist_ok=True)
    with _connect(target) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO node(id, type, name, parent_id, created_at) VALUES (?,?,?,?,?)",
            (
                (n.id, n.type, n.name, n.parent_id, n.created_at.isoformat())
                for n in iter_nodes(layout)
            ),
        )
        conn.executemany(
            "INSERT INTO edge"
            "(id, type, source_id, target_id, source_port_id, target_port_id)"
            " VALUES (?,?,?,?,?,?)",
            (
                (e.id, e.type, e.source_id, e.target_id, e.source_port_id, e.target_port_id)
                for e in iter_edges(layout)
            ),
        )
        conn.executemany(
            "INSERT INTO port(id, node_id, name, direction, port_type) VALUES (?,?,?,?,?)",
            (
                (p.id, p.node_id, p.name, p.direction, p.port_type)
                for p in iter_ports(layout)
            ),
        )


def table_counts(layout: ProjectLayout) -> dict[str, int]:
    """Return row counts for the index tables, or empty dict if no index file."""
    target = index_path(layout)
    if not target.exists():
        return {}
    with _connect(target) as conn:
        out: dict[str, int] = {}
        for table in ("node", "edge", "port"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            out[table] = int(row[0])
        return out


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
