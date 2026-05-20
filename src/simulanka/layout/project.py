from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from simulanka import __version__
from simulanka.kernel.ids import new_id
from simulanka.kernel.manifest import (
    EMPTY_CONTENT_HASH,
    REGISTRY_VERSION,
    SCHEMA_VERSION,
    Manifest,
    load_manifest,
    write_manifest,
)

DIR_NAME = ".simulanka"

GITIGNORE_BODY = """\
# Simulanka local-only state
indexes/
cache/
logs/
"""

# Top-level project root ignore: artifacts directory lives under .simulanka/,
# the other managed dirs (src/, tests/, ...) are part of the user's repo.
ROOT_GITIGNORE_FRAGMENT = """\
# Simulanka internals
.simulanka/
"""


@dataclass(frozen=True)
class ProjectLayout:
    root: Path

    @property
    def dot_dir(self) -> Path:
        return self.root / DIR_NAME

    @property
    def manifest_path(self) -> Path:
        return self.dot_dir / "manifest.json"

    @property
    def graph_dir(self) -> Path:
        return self.dot_dir / "graph"

    @property
    def nodes_dir(self) -> Path:
        return self.graph_dir / "nodes"

    @property
    def edges_dir(self) -> Path:
        return self.graph_dir / "edges"

    @property
    def ports_dir(self) -> Path:
        return self.graph_dir / "ports"

    @property
    def events_dir(self) -> Path:
        return self.graph_dir / "events"

    @property
    def indexes_dir(self) -> Path:
        return self.graph_dir / "indexes"

    @property
    def logs_dir(self) -> Path:
        return self.dot_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.dot_dir / "cache"

    def exists(self) -> bool:
        return self.manifest_path.is_file()

    def load_manifest(self) -> Manifest:
        return load_manifest(self)

    @classmethod
    def discover(cls, start: Path | None = None) -> ProjectLayout | None:
        env = os.environ.get("SIMULANKA_PROJECT")
        if env:
            candidate = cls(Path(env).resolve())
            return candidate if candidate.exists() else None
        cur = (start or Path.cwd()).resolve()
        for ancestor in (cur, *cur.parents):
            if (ancestor / DIR_NAME / "manifest.json").is_file():
                return cls(ancestor)
        return None

    @classmethod
    def require(cls, start: Path | None = None) -> ProjectLayout:
        found = cls.discover(start)
        if found is None:
            raise FileNotFoundError(
                "No Simulanka project found. Run `simulanka init` first, "
                "or set SIMULANKA_PROJECT."
            )
        return found


InitStatus = Literal["created", "already_initialized"]


@dataclass(frozen=True)
class InitResult:
    layout: ProjectLayout
    status: InitStatus
    manifest: Manifest


def init_project(root: Path, *, with_scaffold: bool = True) -> InitResult:
    """Create ``.simulanka/`` under *root*. Idempotent.

    When ``with_scaffold`` is true (the default), also creates the managed
    top-level directories (src/, tests/, docs/, papers/, baselines/ and
    .simulanka/artifacts/) and registers a directory node for each.
    """
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    layout = ProjectLayout(root)

    if layout.exists():
        return InitResult(
            layout=layout,
            status="already_initialized",
            manifest=layout.load_manifest(),
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

    manifest = Manifest(
        schema_version=SCHEMA_VERSION,
        registry_version=REGISTRY_VERSION,
        graph_version=0,
        kernel_version=__version__,
        project_id=new_id("prj"),
        created_at=datetime.now(timezone.utc),
        content_hash=EMPTY_CONTENT_HASH,
    )
    write_manifest(layout, manifest)

    gitignore = layout.dot_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE_BODY, encoding="utf-8")

    if with_scaffold:
        _scaffold_managed_layout(layout)
        manifest = layout.load_manifest()  # refresh after the commit

    return InitResult(layout=layout, status="created", manifest=manifest)


def _scaffold_managed_layout(layout: ProjectLayout) -> None:
    """Create top-level managed dirs and register them as directory nodes."""
    # Imported here to avoid a circular import at module load time.
    from simulanka.kernel.apply import apply_patch
    from simulanka.kernel.intent import (
        CreateNodeOp,
        IntentOp,
        PatchIntent,
    )
    from simulanka.registry.file_kinds import FILE_KINDS

    ops: list[IntentOp] = []
    for kind, spec in FILE_KINDS.items():
        # Filesystem side.
        (layout.root / spec.dir_name).mkdir(parents=True, exist_ok=True)
        # Graph side: one directory node per kind, distinguished by
        # `attrs.managed_kind`. Name is the basename of the directory.
        ops.append(
            CreateNodeOp(
                type="directory",
                name=spec.dir_name.split("/")[-1],
                parent=None,
                attrs={
                    "fs_path": spec.dir_name,
                    "managed_kind": kind,
                },
            )
        )

    apply_patch(
        layout,
        PatchIntent(
            ops=ops,
            actor="system:init",
            base_graph_version=0,
            note="Initial managed-layout scaffold.",
        ),
    )
