"""Synchronous shell-command run executor.

Records each invocation as a ``run`` graph node plus two ``file`` nodes (stdout
and stderr logs) connected via ``produces`` edges. The run is executed inline:
this module deliberately blocks until the subprocess finishes, then commits all
of the bookkeeping in two consecutive patches (nodes first, then edges).

What the runner does **not** do (Alpha):

* No live status. The ``run`` node is written once at the end with its final
  status; if the host process dies mid-run, nothing is committed.
* No automatic detection of user-written output files. Anything the script
  writes to its workdir (other than the captured logs) is the user's
  responsibility — register it manually via ``simulanka graph file register``.
* No agent-specific orchestration. ``agent="shell"`` (default) just runs the
  command; ``agent="codex"`` / ``agent="claude"`` is a label for record-keeping
  only — those wrappers are a separate, later layer on top of this one.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ulid import ULID

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp, PatchIntent
from simulanka.kernel.resolver import resolve_node
from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import load_node

RunStatus = Literal["running", "done", "failed", "timed_out"]


class RunnerError(RuntimeError):
    """Raised when the runner cannot honor the request (bad parent, etc.)."""


@dataclass(frozen=True)
class ExecResult:
    run_node_id: str
    status: RunStatus
    exit_code: int | None
    stdout_path: str
    stderr_path: str
    run_dir: Path
    duration_seconds: float


def exec_run(
    layout: ProjectLayout,
    *,
    command: str,
    parent: str,
    name: str,
    workdir: Path | None = None,
    timeout: float | None = None,
    agent: str = "shell",
    env: dict[str, str] | None = None,
    actor: str = "runner",
) -> ExecResult:
    """Run *command* (shell-interpreted) synchronously and record it in the graph.

    Args:
        layout: target project layout.
        command: shell command line (passed to ``sh -c``).
        parent: selector for the directory or experiment under which the run is
            recorded. Required — every run lives in some context.
        name: name for the run node, unique within the parent.
        workdir: cwd for the subprocess. Defaults to the project root.
        timeout: seconds before the run is killed and reported as ``timed_out``.
        agent: free-form label (``shell``/``codex``/``claude``/...).
        env: subprocess environment overrides (merged with the parent env).
        actor: actor string recorded in the commit events.
    """
    parent_node = _resolve_parent(layout, parent)
    log_parent_node = _nearest_directory(layout, parent_node)

    # Pre-allocate a directory handle (separate from the eventual node id) so
    # the on-disk run dir is unique and stable for the lifetime of this call.
    run_handle = str(ULID())
    run_dir = layout.dot_dir / "runs" / run_handle
    run_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    effective_workdir = (workdir or layout.root).resolve()

    started_at = datetime.now(UTC)
    completed: subprocess.CompletedProcess[bytes] | None = None
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(effective_workdir),
            capture_output=True,
            timeout=timeout,
            env=_merged_env(env),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_bytes = exc.stdout or b""
        stderr_bytes = exc.stderr or b""
    ended_at = datetime.now(UTC)

    if completed is not None:
        stdout_bytes = completed.stdout
        stderr_bytes = completed.stderr
        exit_code: int | None = completed.returncode
        status: RunStatus = "done" if exit_code == 0 else "failed"
    else:
        exit_code = None
        status = "timed_out"

    stdout_log.write_bytes(stdout_bytes)
    stderr_log.write_bytes(stderr_bytes)

    stdout_rel = str(stdout_log.relative_to(layout.root)).replace("\\", "/")
    stderr_rel = str(stderr_log.relative_to(layout.root)).replace("\\", "/")
    workdir_rel = _maybe_relative(effective_workdir, layout.root)

    run_attrs = {
        "command": command,
        "agent": agent,
        "status": status,
        "exit_code": exit_code,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": (ended_at - started_at).total_seconds(),
        "workdir": workdir_rel,
        "stdout_path": stdout_rel,
        "stderr_path": stderr_rel,
        "run_handle": run_handle,
    }

    nodes_intent = PatchIntent(
        ops=[
            CreateNodeOp(
                type="run",
                name=name,
                parent=parent_node.id,
                attrs=run_attrs,
            ),
            CreateNodeOp(
                type="file",
                name=f"{name}.stdout.log",
                parent=log_parent_node.id,
                attrs=_log_file_attrs(stdout_bytes, stdout_rel),
            ),
            CreateNodeOp(
                type="file",
                name=f"{name}.stderr.log",
                parent=log_parent_node.id,
                attrs=_log_file_attrs(stderr_bytes, stderr_rel),
            ),
        ],
        actor=actor,
        base_graph_version=layout.load_manifest().graph_version,
        note=f"runner: exec {name} ({status})",
    )
    nodes_receipt = apply_patch(layout, nodes_intent)
    run_node_id, stdout_node_id, stderr_node_id = nodes_receipt.nodes

    edges_intent = PatchIntent(
        ops=[
            CreateEdgeOp(type="produces", source=run_node_id, target=stdout_node_id),
            CreateEdgeOp(type="produces", source=run_node_id, target=stderr_node_id),
        ],
        actor=actor,
        base_graph_version=layout.load_manifest().graph_version,
        note=f"runner: produces edges for {name}",
    )
    apply_patch(layout, edges_intent)

    return ExecResult(
        run_node_id=run_node_id,
        status=status,
        exit_code=exit_code,
        stdout_path=stdout_rel,
        stderr_path=stderr_rel,
        run_dir=run_dir,
        duration_seconds=run_attrs["duration_seconds"],  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_parent(layout: ProjectLayout, selector: str) -> Node:
    try:
        node = resolve_node(layout, selector)
    except ValueError as exc:
        raise RunnerError(f"--parent {selector!r}: {exc}") from exc
    if node.type not in {"directory", "experiment"}:
        raise RunnerError(
            f"--parent {selector!r}: must point at a `directory` or `experiment` "
            f"node (got `{node.type}`)."
        )
    return node


def _nearest_directory(layout: ProjectLayout, start: Node) -> Node:
    """Walk parents until we hit a node of type `directory` (file nodes need one)."""
    cur: Node | None = start
    while cur is not None:
        if cur.type == "directory":
            return cur
        if cur.parent_id is None:
            break
        cur = load_node(layout, cur.parent_id)
    raise RunnerError(
        f"could not find a `directory` ancestor for {start.id!r}; "
        "file nodes for stdout/stderr require a directory parent."
    )


def _log_file_attrs(content: bytes, rel_path: str) -> dict[str, object]:
    return {
        "fs_path": rel_path,
        "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
        "kind": "run_log",
        "binding": "managed",
        "size_bytes": len(content),
    }


def _log_file_attrs_from_path(path: Path, rel_path: str) -> dict[str, object]:
    """Like :func:`_log_file_attrs` but streams the file from disk.

    Avoids loading the entire log into memory, which matters for long-running
    training jobs whose stdout/stderr can run to hundreds of MB.
    """
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return {
        "fs_path": rel_path,
        "content_hash": "sha256:" + digest.hexdigest(),
        "kind": "run_log",
        "binding": "managed",
        "size_bytes": path.stat().st_size,
    }


def _maybe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root.resolve())).replace("\\", "/") or "."
    except ValueError:
        return str(path)


def _merged_env(overrides: dict[str, str] | None) -> dict[str, str] | None:
    if overrides is None:
        return None
    return {**os.environ, **overrides}
