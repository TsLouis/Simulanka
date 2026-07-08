from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout
from simulanka.registry.file_kinds import FILE_KINDS, FileKindSpec
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import iter_nodes

REFERENCE_HASH_SENTINEL = "sha256:reference"
"""Reference-binding nodes record this in place of a content hash.

Reference kinds (e.g. `baseline`) point at external/large/live trees we don't
own — hashing their bytes would be slow and meaningless (the hash drifts every
time upstream changes). Doctor checks existence only for these nodes.
"""


class FileRegistryError(ValueError):
    """Raised when a file operation violates registry policy."""


@dataclass(frozen=True)
class FileResult:
    node_id: str
    fs_path: Path
    relative_path: str
    kind: str


def create_file(
    layout: ProjectLayout,
    kind: str,
    name: str,
    content: bytes = b"",
    *,
    actor: str = "user",
) -> FileResult:
    """Create a new managed file at the policy-determined path and register it.

    Refuses if the kind is reference-only or the target path already exists.
    """
    spec = _spec_or_error(kind)
    if spec.binding != "managed":
        raise FileRegistryError(
            f"kind=`{kind}` is `{spec.binding}`; use `file register` for an existing path."
        )
    rel = _derive_relative_path(spec, name)
    abs_path = layout.root / rel
    if abs_path.exists():
        raise FileRegistryError(f"`{rel}` already exists.")
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    return _commit_file_node(layout, spec, rel, content, actor=actor)


def register_file(
    layout: ProjectLayout,
    kind: str,
    path: Path,
    *,
    actor: str = "user",
) -> FileResult:
    """Register an existing file (or directory, for reference kinds) into the graph."""
    spec = _spec_or_error(kind)
    # Normalize `..`/`.` without following symlinks: reference-kind entries
    # (e.g. baselines/DS_r → /home/ts/mnt/remote/DS_r) must still count as
    # in-project for the containment check below. `.resolve()` would follow
    # the symlink to its target and reject any external reference.
    in_project = Path(os.path.normpath((layout.root / path).absolute()))
    root_abs = Path(os.path.normpath(layout.root.absolute()))
    try:
        rel_path = in_project.relative_to(root_abs)
    except ValueError as exc:
        raise FileRegistryError(
            f"`{path}` is outside the project root `{layout.root}`."
        ) from exc
    abs_path = in_project.resolve()
    rel = str(rel_path)
    rel_str = rel.replace("\\", "/")

    if not abs_path.exists():
        raise FileRegistryError(f"`{rel_str}` does not exist on disk.")

    # Path must live under the kind's managed directory.
    expected_root = spec.dir_name.rstrip("/") + "/"
    if not (rel_str == spec.dir_name or rel_str.startswith(expected_root)):
        raise FileRegistryError(
            f"`{rel_str}` is not under managed dir `{spec.dir_name}` for kind `{kind}`."
        )

    if spec.binding == "managed":
        if not abs_path.is_file():
            raise FileRegistryError(f"`{rel_str}` is not a regular file.")
        content = abs_path.read_bytes()
    else:  # reference: file or directory both OK
        content = b""  # hash is computed below specially

    return _commit_file_node(
        layout, spec, rel_str, content, actor=actor, abs_path=abs_path,
    )


def _commit_file_node(
    layout: ProjectLayout,
    spec: FileKindSpec,
    rel_path: str,
    content: bytes,
    *,
    actor: str,
    abs_path: Path | None = None,
) -> FileResult:
    parent = _find_managed_dir_node(layout, spec)
    if abs_path is None:
        abs_path = layout.root / rel_path

    if spec.binding == "reference":
        hash_str = REFERENCE_HASH_SENTINEL
        size: int | None = None
    else:
        hash_str = "sha256:" + hashlib.sha256(content).hexdigest()
        size = len(content)

    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(
                    type="file",
                    name=Path(rel_path).name,
                    parent=parent.id,
                    attrs={
                        "fs_path": rel_path,
                        "content_hash": hash_str,
                        "kind": spec.name,
                        "binding": spec.binding,
                        "size_bytes": size,
                    },
                )
            ],
            actor=actor,
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    return FileResult(
        node_id=receipt.nodes[0],
        fs_path=abs_path,
        relative_path=rel_path,
        kind=spec.name,
    )


def managed_dir_node(layout: ProjectLayout, kind: str) -> Node:
    """Resolve (lazily creating) the managed top-level directory node for `kind`.

    Public entry for callers that commit file nodes inside their own
    PatchIntent (plan ingest) instead of going through create/register_file.
    """
    return _find_managed_dir_node(layout, _spec_or_error(kind))


def find_file_nodes_under_kind(layout: ProjectLayout, kind: str) -> list[Node]:
    return [
        n for n in iter_nodes(layout)
        if n.type == "file" and n.attrs.get("kind") == kind
    ]


def _spec_or_error(kind: str) -> FileKindSpec:
    spec = FILE_KINDS.get(kind)
    if spec is None:
        raise FileRegistryError(
            f"Unknown file kind `{kind}`. Known: {sorted(FILE_KINDS)}."
        )
    return spec


def _derive_relative_path(spec: FileKindSpec, name: str) -> str:
    fname = name
    if spec.name_prefix and not fname.startswith(spec.name_prefix):
        fname = spec.name_prefix + fname
    if spec.default_extension and "." not in Path(fname).name:
        fname = fname + spec.default_extension
    return f"{spec.dir_name}/{fname}"


def _find_managed_dir_node(layout: ProjectLayout, spec: FileKindSpec) -> Node:
    # Primary match is `fs_path` — kinds may share a directory (plan/brief both
    # live under `research/`), so `managed_kind` can no longer be the key. The
    # attr fallback keeps graphs from before `fs_path` existed resolving.
    for n in iter_nodes(layout):
        if n.type == "directory" and n.parent_id is None and (
            n.attrs.get("fs_path") == spec.dir_name
            or n.attrs.get("managed_kind") == spec.name
        ):
            return n

    # Kinds added after a project was scaffolded (e.g. §14's plan/brief on an
    # older graph) create their managed dir lazily instead of demanding a
    # migrate step.
    if spec.binding == "managed":
        (layout.root / spec.dir_name).mkdir(parents=True, exist_ok=True)
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateNodeOp(
                    type="directory",
                    name=spec.dir_name.split("/")[-1],
                    parent=None,
                    attrs={"fs_path": spec.dir_name},
                )
            ],
            actor="system:file-registry",
            base_graph_version=layout.load_manifest().graph_version,
            note=f"Lazily created managed dir `{spec.dir_name}` for kind `{spec.name}`.",
        ),
    )
    from simulanka.storage.entity_store import load_node

    return load_node(layout, receipt.nodes[0])


