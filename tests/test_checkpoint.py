"""Tests for the embedded .simulanka/ git checkpoint repo (§13.6 撤回兜底)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.storage import checkpoint as cp


def _apply_create(layout: ProjectLayout, name: str) -> None:
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name=name)],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
            note=f"create {name}",
        ),
    )


def _commit_count(layout: ProjectLayout) -> int:
    out = subprocess.run(
        ["git", "-C", str(layout.dot_dir), "rev-list", "--count", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return int(out.stdout.strip())


def test_apply_patch_without_repo_is_noop(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _apply_create(layout, "a")
    assert not (layout.dot_dir / ".git").exists()


def test_ensure_repo_idempotent_and_initial_snapshot(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    cp.ensure_repo(layout)
    assert cp.repo_exists(layout)
    assert _commit_count(layout) == 1

    cp.ensure_repo(layout)  # second call must not re-init or commit
    assert _commit_count(layout) == 1


def test_checkpoint_clean_tree_returns_false(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    cp.ensure_repo(layout)
    assert cp.checkpoint(layout, "noop") is False
    assert _commit_count(layout) == 1


def test_apply_patch_with_repo_commits_each_version(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    cp.ensure_repo(layout)
    base = _commit_count(layout)

    _apply_create(layout, "a")
    _apply_create(layout, "b")
    assert _commit_count(layout) == base + 2

    # Commit message carries graph version + actor + note.
    out = subprocess.run(
        ["git", "-C", str(layout.dot_dir), "log", "-1", "--format=%s"],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "v2 test: create b"


def test_ignored_dirs_stay_untracked(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    (layout.indexes_dir / "graph.sqlite").write_bytes(b"derived")
    (layout.cache_dir / "blob").write_bytes(b"cached")
    (layout.logs_dir / "run.log").write_text("log", encoding="utf-8")
    cp.ensure_repo(layout)

    out = subprocess.run(
        ["git", "-C", str(layout.dot_dir), "ls-files"],
        capture_output=True, text=True, check=True,
    )
    tracked = out.stdout.splitlines()
    assert not any(p.startswith(("graph/indexes/", "cache/", "logs/")) for p in tracked)
    assert "manifest.json" in tracked


def test_checkpoint_failure_does_not_break_apply_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    cp.ensure_repo(layout)

    def boom(
        layout: ProjectLayout, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(128, ["git"], stderr="simulated")

    monkeypatch.setattr(cp, "_git", boom)
    _apply_create(layout, "a")  # must not raise
    assert layout.load_manifest().graph_version == 1


def test_tag_checkpoint_moves_with_force(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    cp.ensure_repo(layout)
    cp.tag_checkpoint(layout, "discuss-r1-start")
    _apply_create(layout, "a")
    cp.tag_checkpoint(layout, "discuss-r1-start")  # re-tag = move, no error

    out = subprocess.run(
        ["git", "-C", str(layout.dot_dir), "tag", "--points-at", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    assert "discuss-r1-start" in out.stdout.splitlines()
