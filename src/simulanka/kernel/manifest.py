from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from simulanka.layout.project import ProjectLayout

SCHEMA_VERSION = 1
REGISTRY_VERSION = 1
EMPTY_CONTENT_HASH = "sha256:" + hashlib.sha256(b"").hexdigest()


class Manifest(BaseModel):
    schema_version: int
    registry_version: int
    graph_version: int
    kernel_version: str
    project_id: str
    created_at: datetime
    content_hash: str


def load_manifest(layout: ProjectLayout) -> Manifest:
    return Manifest.model_validate_json(layout.manifest_path.read_text("utf-8"))


def write_manifest(layout: ProjectLayout, manifest: Manifest) -> None:
    payload = json.loads(manifest.model_dump_json())
    _atomic_write_json(layout.manifest_path, payload)


def compute_content_hash(layout: ProjectLayout) -> str:
    """sha256 of sorted ``<id> <sha256(file)>`` lines across all entity files."""
    lines: list[str] = []
    for d in (layout.nodes_dir, layout.edges_dir, layout.ports_dir):
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if not entry.is_file() or entry.suffix != ".json":
                continue
            digest = hashlib.sha256(entry.read_bytes()).hexdigest()
            lines.append(f"{entry.stem} {digest}")
    rolled = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return "sha256:" + rolled


def _atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
