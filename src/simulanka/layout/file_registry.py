from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout
from simulanka.registry.file_kinds import FILE_KINDS, FileKindSpec
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import iter_nodes


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
    abs_path = (layout.root / path).resolve()
    try:
        rel_path = abs_path.relative_to(layout.root.resolve())
    except ValueError as exc:
        raise FileRegistryError(
            f"`{path}` is outside the project root `{layout.root}`."
        ) from exc
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
    parent = _find_managed_dir_node(layout, spec.name)
    if abs_path is None:
        abs_path = layout.root / rel_path

    if spec.binding == "reference" and abs_path.is_dir():
        hash_str = _hash_directory(abs_path)
        size: int | None = None
    else:
        hash_str = "sha256:" + hashlib.sha256(content).hexdigest()
        size = len(content) if spec.binding == "managed" else abs_path.stat().st_size

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


def _find_managed_dir_node(layout: ProjectLayout, kind: str) -> Node:
    for n in iter_nodes(layout):
        if (
            n.type == "directory"
            and n.parent_id is None
            and n.attrs.get("managed_kind") == kind
        ):
            return n
    raise FileRegistryError(
        f"Managed-dir node for kind `{kind}` not found. "
        "Was the project initialized with scaffolding?"
    )


def _hash_directory(root: Path) -> str:
    """Stable hash over a directory's file contents (sorted relative paths)."""
    h = hashlib.sha256()
    for entry in sorted(root.rglob("*")):
        if entry.is_file():
            h.update(str(entry.relative_to(root)).encode("utf-8"))
            h.update(b"\0")
            h.update(hashlib.sha256(entry.read_bytes()).digest())
    return "sha256:" + h.hexdigest()
