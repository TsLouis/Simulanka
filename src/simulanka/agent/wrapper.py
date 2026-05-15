"""Translate (agent, prompt) into a CLI invocation and ride on the run executor.

Design intent: keep this layer *thin* and loosely coupled.

* The wrapper does **not** manage the agent's capabilities (skills, MCP servers,
  prompt scaffolding, tool allow-lists). Those live in the agent's own
  configuration — ``~/.codex/config.toml``, ``~/.claude/CLAUDE.md``, etc.
  Whatever the user has set up there is automatically in effect because we
  just invoke the binary in their workspace.
* The wrapper does **not** parse the agent's output. stdout/stderr are captured
  raw via the underlying ``exec_run`` — agent-specific formats (jsonl streams,
  tool-call traces, ...) change too fast to depend on.
* The wrapper records *which files were touched* by snapshotting the workspace
  before and after. The diff is written to ``.simulanka/runs/<handle>/changes.json``
  for audit; it is **not** auto-registered into the graph as ``file`` nodes,
  because deciding the right ``kind`` (code / config / baseline / artifact)
  is a judgment call.

Adding a new agent type or adapting to a CLI change: extend ``AGENT_TEMPLATES``
or override via the environment variable ``SIMULANKA_AGENT_<NAME>_ARGV`` (a
shell-quoted string with ``{prompt}`` as the placeholder).
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from simulanka.layout.project import ProjectLayout
from simulanka.runner import exec_run

# ---------------------------------------------------------------------------
# Built-in agent templates
# ---------------------------------------------------------------------------
# Each template is an argv list. ``{prompt}`` in any element is replaced with
# the user's prompt (no shell interpolation — substitution is positional).
#
# These defaults are starting points only. If codex or claude change their
# invocation format, override the relevant entry here or set the env var
# ``SIMULANKA_AGENT_<UPPERCASE_NAME>_ARGV='binary --flag {prompt}'``.

AGENT_TEMPLATES: dict[str, list[str]] = {
    "codex": ["codex", "exec", "{prompt}"],
    "claude": ["claude", "-p", "{prompt}"],
}

# Filesystem entries that are noise for diff purposes (caches, VCS, our own
# bookkeeping, common venv/build dirs). The list is intentionally short and
# conservative — users with unusual layouts can pass ``track_scope`` to narrow
# the snapshot to a subdirectory.
_DEFAULT_DIFF_IGNORE = frozenset({
    ".simulanka", ".git", ".hg", ".svn",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", ".venv", "venv", ".tox",
})


class AgentError(RuntimeError):
    """Raised when the wrapper cannot produce a valid invocation."""


@dataclass(frozen=True)
class AgentRunResult:
    run_node_id: str
    status: str
    exit_code: int | None
    run_dir: Path
    prompt_path: str
    changes_path: str
    files_added: list[str]
    files_modified: list[str]
    files_deleted: list[str]
    duration_seconds: float


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_agent(
    layout: ProjectLayout,
    *,
    agent: str,
    prompt: str,
    parent: str,
    name: str,
    workdir: Path | None = None,
    timeout: float | None = None,
    extra_args: list[str] | None = None,
    track_scope: list[str] | None = None,
    actor: str = "runner:agent",
) -> AgentRunResult:
    """Invoke an external agent CLI and record the run + workspace diff.

    Args:
        agent: short name. Looks up ``AGENT_TEMPLATES`` (or env override).
        prompt: the task to send. Substituted into the argv template.
        parent: directory/experiment selector for the resulting run node.
        workdir: agent cwd. Defaults to the project root.
        timeout: subprocess timeout in seconds.
        extra_args: appended to the argv before substitution (positional).
        track_scope: subdirectories (relative to workdir) to snapshot. Defaults
            to the workdir root. Useful when the project contains huge data
            directories you don't want to hash on every run.
    """
    template = _resolve_template(agent)
    argv = [_fill(part, prompt) for part in template]
    if extra_args:
        argv.extend(extra_args)
    command = shlex.join(argv)

    effective_workdir = (workdir or layout.root).resolve()
    scope_dirs = _resolve_scope(effective_workdir, track_scope)
    before = _snapshot(scope_dirs)

    exec_result = exec_run(
        layout,
        command=command,
        parent=parent,
        name=name,
        workdir=effective_workdir,
        timeout=timeout,
        agent=agent,
        actor=actor,
    )

    after = _snapshot(scope_dirs)
    diff = _diff(before, after, base=layout.root)

    prompt_path = exec_result.run_dir / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    changes_path = exec_result.run_dir / "changes.json"
    changes_path.write_text(
        json.dumps(
            {
                "agent": agent,
                "argv": argv,
                "workdir": str(effective_workdir),
                "track_scope": [str(p) for p in scope_dirs],
                **diff,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return AgentRunResult(
        run_node_id=exec_result.run_node_id,
        status=exec_result.status,
        exit_code=exec_result.exit_code,
        run_dir=exec_result.run_dir,
        prompt_path=str(prompt_path.relative_to(layout.root)),
        changes_path=str(changes_path.relative_to(layout.root)),
        files_added=diff["added"],
        files_modified=diff["modified"],
        files_deleted=diff["deleted"],
        duration_seconds=exec_result.duration_seconds,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_template(agent: str) -> list[str]:
    env_key = f"SIMULANKA_AGENT_{agent.upper()}_ARGV"
    override = os.environ.get(env_key)
    if override:
        try:
            return shlex.split(override)
        except ValueError as exc:
            raise AgentError(f"{env_key} is not valid shell syntax: {exc}") from exc
    template = AGENT_TEMPLATES.get(agent)
    if template is None:
        raise AgentError(
            f"Unknown agent {agent!r}. Known: {sorted(AGENT_TEMPLATES)}. "
            f"Set {env_key} to override or add an entry to AGENT_TEMPLATES."
        )
    return list(template)


def _fill(template_part: str, prompt: str) -> str:
    return template_part.replace("{prompt}", prompt)


def _resolve_scope(workdir: Path, scope: list[str] | None) -> list[Path]:
    if not scope:
        return [workdir]
    out: list[Path] = []
    for s in scope:
        p = (workdir / s).resolve()
        if not p.exists():
            raise AgentError(f"track_scope entry {s!r} does not exist under {workdir}.")
        out.append(p)
    return out


def _snapshot(roots: list[Path]) -> dict[str, str]:
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


def _is_ignored(entry: Path, root: Path) -> bool:
    try:
        rel_parts = entry.relative_to(root).parts
    except ValueError:
        return False
    return any(part in _DEFAULT_DIFF_IGNORE for part in rel_parts)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _diff(
    before: dict[str, str], after: dict[str, str], *, base: Path,
) -> dict[str, list[str]]:
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


# Re-exposed for callers who want to invoke exec_run directly with the same
# argv-shaping logic. Most callers should use ``run_agent`` instead.
def build_command(agent: str, prompt: str, extra_args: list[str] | None = None) -> str:
    """Public helper: return the shell command string an agent invocation would use."""
    template = _resolve_template(agent)
    argv = [_fill(part, prompt) for part in template]
    if extra_args:
        argv.extend(extra_args)
    return shlex.join(argv)
