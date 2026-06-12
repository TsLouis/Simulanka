"""Detached agent run tests: start + lazy diff finalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulanka.agent import (
    AgentError,
    finalize_agent_diff,
    start_agent_run,
)
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.runner import kill_run, start_run, wait_run
from simulanka.storage.entity_store import load_node
from tests.conftest import fake_argv as _fake_argv


def _seed(layout: ProjectLayout) -> None:
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="research")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )


def test_detached_happy_path_finalizes_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)

    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("doomed\n", encoding="utf-8")

    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        _fake_argv(
            f"echo new > {tmp_path}/c.txt; "
            f"echo changed > {tmp_path}/a.txt; "
            f"rm {tmp_path}/b.txt"
        ),
    )

    started = start_agent_run(
        layout,
        agent="fake",
        prompt="do the thing",
        parent="/research",
        name="async1",
    )

    # Pre-finalize, the run dir should already have the meta + snapshot + prompt.
    assert (started.run_dir / "agent_meta.json").exists()
    assert (started.run_dir / "before_snapshot.json").exists()
    assert (started.run_dir / "prompt.txt").read_text(encoding="utf-8") == "do the thing"
    # changes.json should not exist yet — finalization is lazy.
    assert not (started.run_dir / "changes.json").exists()

    finished = wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.05)
    assert finished.attrs["status"] == "done"

    summary = finalize_agent_diff(layout, finished)
    assert summary is not None
    assert "c.txt" in summary.added
    assert "a.txt" in summary.modified
    assert "b.txt" in summary.deleted

    changes = json.loads(
        (started.run_dir / "changes.json").read_text(encoding="utf-8"),
    )
    assert changes["agent"] == "fake"
    assert changes["added"] == ["c.txt"]
    assert changes["modified"] == ["a.txt"]
    assert changes["deleted"] == ["b.txt"]
    assert run_doctor(layout).ok


def test_finalize_idempotent_does_not_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        _fake_argv(f"echo new > {tmp_path}/x.txt"),
    )
    started = start_agent_run(
        layout, agent="fake", prompt="x", parent="/research", name="idem",
    )
    node = wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.05)

    first = finalize_agent_diff(layout, node)
    assert first is not None
    changes_path = started.run_dir / "changes.json"
    mtime_after_first = changes_path.stat().st_mtime_ns

    # Mutate the workspace after the diff is frozen; idempotent finalize
    # must NOT re-hash and must NOT pick up the new file.
    (tmp_path / "post_finalize.txt").write_text("ignored\n", encoding="utf-8")

    second = finalize_agent_diff(layout, node)
    assert second is not None
    assert second.added == first.added
    assert "post_finalize.txt" not in second.added
    assert changes_path.stat().st_mtime_ns == mtime_after_first


def test_finalize_on_non_agent_run_returns_none(tmp_path: Path) -> None:
    """Plain `start_run` (no agent metadata) → finalize should be a no-op."""
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    started = start_run(
        layout, command="echo plain", parent="/research", name="plain",
    )
    node = wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.05)
    assert finalize_agent_diff(layout, node) is None
    run_dir = layout.dot_dir / "runs" / str(node.attrs["run_handle"])
    assert not (run_dir / "changes.json").exists()


def test_finalize_while_running_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    monkeypatch.setenv("SIMULANKA_AGENT_FAKE_ARGV", _fake_argv("sleep 5"))
    started = start_agent_run(
        layout, agent="fake", prompt="wait", parent="/research", name="slow",
    )
    try:
        node = load_node(layout, started.run_node_id)
        # The run may already be done if the harness was very slow to schedule
        # us. Only assert the "still running" contract when that's actually true.
        if node.attrs.get("status") == "running":
            assert finalize_agent_diff(layout, node) is None
            assert not (started.run_dir / "changes.json").exists()
    finally:
        kill_run(layout, started.run_node_id)
        wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.1)


def test_kill_finalizes_diff_with_partial_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    # Write one file fast, then sleep until killed — diff should still see it.
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        _fake_argv(f"echo partial > {tmp_path}/partial.txt; sleep 30"),
    )
    started = start_agent_run(
        layout, agent="fake", prompt="long", parent="/research", name="killed",
    )
    # Give the subprocess a moment to write the file.
    import time
    time.sleep(0.3)

    kill_run(layout, started.run_node_id)
    node = wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.1)
    assert node.attrs["status"] == "failed"

    summary = finalize_agent_diff(layout, node)
    assert summary is not None
    assert "partial.txt" in summary.added


def test_track_scope_persists_through_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    (tmp_path / "watched").mkdir()
    (tmp_path / "ignored").mkdir()
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        _fake_argv(
            f"echo w > {tmp_path}/watched/new.txt; "
            f"echo i > {tmp_path}/ignored/new.txt"
        ),
    )
    started = start_agent_run(
        layout,
        agent="fake",
        prompt="scoped",
        parent="/research",
        name="scoped",
        track_scope=["watched"],
    )
    node = wait_run(layout, started.run_node_id, timeout=10.0, poll_interval=0.05)
    summary = finalize_agent_diff(layout, node)
    assert summary is not None
    assert "watched/new.txt" in summary.added
    assert not any("ignored" in p for p in summary.added)


def test_detached_track_scope_escaping_workdir_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "proj"
    layout = init_project(project, with_scaffold=False).layout
    _seed(layout)
    (tmp_path / "outside").mkdir()
    monkeypatch.setenv("SIMULANKA_AGENT_FAKE_ARGV", "true {prompt}")
    with pytest.raises(AgentError, match="escapes workdir"):
        start_agent_run(
            layout,
            agent="fake",
            prompt="x",
            parent="/research",
            name="escape_scope",
            track_scope=["../outside"],
        )
