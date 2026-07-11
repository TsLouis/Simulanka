"""Workspace snapshot + diff: the system's single measurement path.

Every execution bracket — sync agent wrapper, detached agent, human `run
begin/end` — measures "which files did this run touch" the same way: hash
every file in scope before, hash again after, compare. A snapshot is a flat
``{absolute_path: sha256-hex}`` mapping; it deliberately records *paths and
hashes only*, never content. The system can always answer "what changed",
not "what the change was" — content-level diffing is delegated to git when
the workdir is a repository (worktree-per-run makes that the common case).

This module knows nothing of the graph, the runner, or agents. Errors are
plain ``ValueError``; callers wrap them in their own error types.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

DEFAULT_DIFF_IGNORE = frozenset({
    ".simulanka", ".git", ".hg", ".svn",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", ".venv", "venv", ".tox",
})


def resolve_scope(workdir: Path, scope: list[str] | None) -> list[Path]:
    """Expand *scope* entries (relative to *workdir*) into absolute roots.

    ``None``/empty scope means the whole workdir. Entries must exist and may
    not escape the workdir.
    """
    if not scope:
        return [workdir]
    base = workdir.resolve()
    out: list[Path] = []
    for s in scope:
        p = (workdir / s).resolve()
        if not p.is_relative_to(base):
            raise ValueError(f"track_scope entry {s!r} escapes workdir {workdir}.")
        if not p.exists():
            raise ValueError(f"track_scope entry {s!r} does not exist under {workdir}.")
        out.append(p)
    return out


def snapshot_workspace(roots: list[Path]) -> dict[str, str]:
    """Hash every file under each root. Returns {abs_path: sha256-hex}."""
    out: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            out[str(root)] = _file_hash(root)
            continue
        for entry in root.rglob("*"):
            if not entry.is_file():
                continue
            if _is_ignored(entry, root):
                continue
            out[str(entry)] = _file_hash(entry)
    return out


def diff_snapshots(
    before: dict[str, str], after: dict[str, str], *, base: Path,
) -> dict[str, list[str]]:
    """Compare two snapshots; paths in the result are relative to *base*."""
    before_keys = set(before)
    after_keys = set(after)
    added = sorted(after_keys - before_keys)
    deleted = sorted(before_keys - after_keys)
    modified = sorted(
        p for p in (before_keys & after_keys) if before[p] != after[p]
    )

    def rel(p: str) -> str:
        try:
            return str(Path(p).relative_to(base)).replace("\\", "/")
        except ValueError:
            return p

    return {
        "added": [rel(p) for p in added],
        "modified": [rel(p) for p in modified],
        "deleted": [rel(p) for p in deleted],
    }


def _is_ignored(entry: Path, root: Path) -> bool:
    try:
        rel_parts = entry.relative_to(root).parts
    except ValueError:
        return False
    return any(part in DEFAULT_DIFF_IGNORE for part in rel_parts)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
