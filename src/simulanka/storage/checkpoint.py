"""Git checkpointing for ``.simulanka/`` (§13.6 撤回兜底).

The graph store has no undo: entities are plain JSON, the event log is
append-only, and the SQLite index is derived. Once an agent holds real-time
write power (verify-discuss loop), every kernel commit needs a recovery
point. We embed an *independent* git repo inside ``.simulanka/`` — separate
from the baseline's code repo so graph snapshots never pollute the user's
code history. ``indexes/``, ``cache/`` and ``logs/`` are ignored via the
``.gitignore`` that ``init_project`` already writes; recovery is
``git checkout`` + ``simulanka graph index rebuild``.

Activation is lazy: ``apply_patch`` checkpoints only if ``.simulanka/.git``
exists, so kernel tests and plain CLI projects pay nothing. The API server
calls ``ensure_repo`` at startup — agent write power only enters through the
server, so the safety net is always live before it matters.
"""

from __future__ import annotations

import logging
import subprocess

from simulanka.layout.project import ProjectLayout

logger = logging.getLogger(__name__)


def _git(layout: ProjectLayout, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(layout.dot_dir), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def repo_exists(layout: ProjectLayout) -> bool:
    return (layout.dot_dir / ".git").is_dir()


def ensure_repo(layout: ProjectLayout) -> None:
    """Init the embedded repo (idempotent) and take an initial snapshot.

    Identity is repo-local so we never touch the user's global git config.
    """
    if repo_exists(layout):
        return
    _git(layout, "init", "-q")
    _git(layout, "config", "user.name", "simulanka")
    _git(layout, "config", "user.email", "simulanka@local")
    _git(layout, "config", "commit.gpgsign", "false")
    checkpoint(layout, "checkpoint: repo init")


def checkpoint(layout: ProjectLayout, message: str) -> bool:
    """Stage everything and commit. Returns False when there was no change."""
    _git(layout, "add", "-A")
    status = _git(layout, "status", "--porcelain")
    if not status.stdout.strip():
        return False
    _git(layout, "commit", "-q", "-m", message)
    return True


def maybe_checkpoint(layout: ProjectLayout, message: str) -> None:
    """Best-effort checkpoint: no-op without a repo, never raises.

    The graph write has already landed when this runs — a broken git must
    not fail the patch. A skipped snapshot only narrows the recovery net,
    so log and move on.
    """
    if not repo_exists(layout):
        return
    try:
        checkpoint(layout, message)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        logger.warning("graph checkpoint failed: %s", detail)


def tag_checkpoint(layout: ProjectLayout, name: str) -> None:
    """Mark the current snapshot (e.g. a discussion-round start). Idempotent:
    re-tagging moves the tag to the current commit."""
    _git(layout, "tag", "-f", name)
