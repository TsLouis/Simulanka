"""Tests for the detached run executor (start/reconcile/wait/kill)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.runner import (
    kill_run,
    reconcile_run,
    start_run,
    wait_run,
)
from simulanka.storage.entity_store import load_node


def _seed(layout: ProjectLayout) -> None:
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="research")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )


def test_start_then_wait_finishes_done(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)

    started = start_run(
        layout,
        command="echo hello",
        parent="/research",
        name="quick",
    )

    # Immediately after start_run, status is 'running' (or already 'done' if
    # the subprocess raced us). Both are acceptable — wait will normalize.
    initial = load_node(layout, started.run_node_id)
    assert initial.attrs["status"] in {"running", "done"}
    assert initial.attrs["detached"] is True

    finished = wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.05)
    assert finished.attrs["status"] == "done"
    assert finished.attrs["exit_code"] == 0
    assert finished.attrs["duration_seconds"] is not None

    # stdout/stderr file nodes have the real content hash now.
    stdout_node = load_node(layout, finished.attrs["stdout_node_id"])
    assert stdout_node.attrs["size_bytes"] > 0
    empty_sha = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert stdout_node.attrs["content_hash"] != empty_sha

    # Logs on disk match what got hashed.
    stdout_bytes = (tmp_path / finished.attrs["stdout_path"]).read_bytes()
    assert stdout_bytes.startswith(b"hello")

    assert run_doctor(layout).ok


def test_failing_command_marked_failed(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)

    started = start_run(
        layout, command="exit 5", parent="/research", name="failing",
    )
    node = wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.05)
    assert node.attrs["status"] == "failed"
    assert node.attrs["exit_code"] == 5
    assert run_doctor(layout).ok


def test_kill_marks_failed_with_null_exit(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)

    started = start_run(
        layout,
        command="sleep 30",
        parent="/research",
        name="long",
    )
    # Give the subprocess a moment to start.
    time.sleep(0.1)

    kill_run(layout, started.run_node_id)

    # Wait until reconcile flips to failed.
    node = wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.1)
    assert node.attrs["status"] == "failed"
    # SIGTERM kills before the wrapper writes finished → exit_code stays None.
    # On some shells the wrapper still completes and writes 143; accept either.
    assert node.attrs["exit_code"] in (None, 143)
    assert run_doctor(layout).ok


def test_reconcile_is_idempotent(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    started = start_run(layout, command="true", parent="/research", name="idem")
    final = wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.05)
    version_after_finalize = layout.load_manifest().graph_version
    # Second reconcile should be a no-op (no new graph version bump).
    again = reconcile_run(layout, started.run_node_id)
    assert again.attrs == final.attrs
    assert layout.load_manifest().graph_version == version_after_finalize


def test_wait_timeout_raises(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    started = start_run(layout, command="sleep 5", parent="/research", name="slow")
    try:
        with pytest.raises(TimeoutError):
            wait_run(layout, started.run_node_id, timeout=0.2, poll_interval=0.05)
    finally:
        # Clean up: don't leave a stray subprocess.
        kill_run(layout, started.run_node_id)
        wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.1)
