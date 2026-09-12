"""Real process/thread contention at graph and server decision boundaries."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.bundle import export_bundle
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.events import iter_events
from simulanka.kernel.intent import CreateNodeOp, UpdateAttrsOp
from simulanka.kernel.manifest import compute_content_hash, write_manifest
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.storage.checkpoint import ensure_repo
from simulanka.storage.entity_store import iter_nodes
from simulanka.storage.write_lock import LOCK_NAME, project_write_lock

# A fresh interpreter for every writer: no inherited lock object or test mocks.
# Parent drives readiness and a gate *after* the version read / first write.
_WORKER = r'''
import json, sys
from pathlib import Path
import simulanka.kernel.apply as apply
import simulanka.kernel.migration as migration
import simulanka.storage.write_lock as locking
from simulanka.kernel.bundle import read_bundle, import_bundle
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.storage.checkpoint import checkpoint, ensure_repo
root, mode, name, gated = sys.argv[1:]
layout = ProjectLayout(Path(root))
if mode == 'accept':
    from fastapi.testclient import TestClient
    from simulanka.server.app import create_app
    client = TestClient(create_app(layout))
def gate():
    print('inside', flush=True)
    assert sys.stdin.readline().strip() == 'release'
if gated == 'read':
    original = apply.load_manifest
    def load(layout):
        result = original(layout)
        gate()
        return result
    apply.load_manifest = load
elif gated == 'write':
    original = apply.save_node
    def save(layout, node):
        gate()
        original(layout, node)
    apply.save_node = save
elif gated == 'lock':
    original = locking._acquire
    def acquire(fd):
        print('attempt', flush=True)
        original(fd)
    locking._acquire = acquire
print('ready', flush=True)
assert sys.stdin.readline().strip() == 'go'
try:
    if mode == 'hold':
        with locking.project_write_lock(layout.root):
            gate()
        result = 'released'
    elif mode == 'now':
        result = apply.apply_patch_now(layout, actor='worker',
            ops=[CreateNodeOp(type='directory', name=name)]).graph_version
    elif mode == 'explicit':
        result = apply.apply_patch(layout, PatchIntent(actor='worker', base_graph_version=0,
            ops=[CreateNodeOp(type='directory', name=name)])).graph_version
    elif mode == 'init':
        result = init_project(layout.root).status
    elif mode == 'import':
        result = str(import_bundle(read_bundle(Path(name)), layout.root).root)
    elif mode == 'migrate':
        result = len(migration.run_migrations(layout).steps)
    elif mode == 'checkpoint':
        ensure_repo(layout)
        result = checkpoint(layout, 'manual checkpoint')
    elif mode == 'accept':
        with client:
            response = client.post('/edge/' + name + '/accept')
            result = {'status': response.status_code, 'body': response.json()}
    elif mode == 'agent_verdict':
        from simulanka.agent.harness import DiscussionOp
        from simulanka.server.agent_ops import apply_agent_ops
        applied, rejected = apply_agent_ops(layout, [DiscussionOp(
            op='set_verdict', edge_id=name,
            attrs={'verdict': 'wrong', 'verdict_note': 'agent check'}, raw={})])
        result = {'applied': applied, 'rejected': rejected}
    else:
        raise AssertionError(mode)
except Exception as exc:
    result = {'error': type(exc).__name__, 'message': str(exc)}
print(json.dumps(result), flush=True)
'''

Process = subprocess.Popen[str]


def _send(proc: Process, message: str) -> None:
    assert proc.stdin is not None
    proc.stdin.write(message + "\n")
    proc.stdin.flush()


def _line(proc: Process, timeout: float = 10) -> str:
    assert proc.stdout is not None
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        assert selector.select(timeout), "writer did not reach the expected gate"
    result: str = proc.stdout.readline().strip()
    if not result:
        assert proc.stderr is not None
        pytest.fail(proc.stderr.read())
    return result


def _result(proc: Process) -> Any:
    value = json.loads(_line(proc))
    assert proc.wait(timeout=10) == 0
    return value


def _blocked(proc: Process) -> None:
    assert proc.stdout is not None
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        assert not selector.select(0.15), "writer crossed the held commit boundary"
    assert proc.poll() is None


@pytest.fixture
def writer() -> Iterator[Callable[..., Process]]:
    if sys.platform == "win32":
        pytest.skip("POSIX pipe readiness gates; Windows lock needs native validation")
    processes: list[Process] = []

    def start(
        root: Path, mode: str, name: str = "worker", gate: str = "none", *, go: bool = True,
    ) -> Process:
        proc = subprocess.Popen(
            [sys.executable, "-c", _WORKER, str(root), mode, name, gate],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(proc)
        assert _line(proc) == "ready"
        if go:
            _send(proc, "go")
        return proc

    yield start
    for proc in processes:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


def _healthy(layout: ProjectLayout, version: int) -> None:
    assert layout.load_manifest().graph_version == version
    assert [event.graph_version for event in iter_events(layout)] == list(range(1, version + 1))
    assert layout.load_manifest().content_hash == compute_content_hash(layout)
    assert not list(layout.graph_dir.rglob("*.tmp"))
    assert run_doctor(layout).ok


def test_same_base_has_one_winner_then_fresh_retry(
    tmp_path: Path, writer: Callable[..., Process],
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    first = writer(tmp_path, "explicit", "first", "read")
    assert _line(first) == "inside"
    second = writer(tmp_path, "explicit", "second", "lock")
    assert _line(second) == "attempt"
    _blocked(second)
    _send(first, "release")
    assert _result(first) == 1
    assert _result(second)["error"] == "VersionConflict"
    assert [node.name for node in iter_nodes(layout)] == ["first"]
    assert _result(writer(tmp_path, "now", "second")) == 2
    _healthy(layout, 2)


def test_live_version_is_read_after_lock_and_checkpoint_is_serial(
    tmp_path: Path, writer: Callable[..., Process],
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    ensure_repo(layout)
    first = writer(tmp_path, "now", "first", "write")
    assert _line(first) == "inside"
    second = writer(tmp_path, "now", "second", "lock")
    assert _line(second) == "attempt"
    _blocked(second)
    _send(first, "release")
    assert _result(first) == 1
    assert _result(second) == 2
    _healthy(layout, 2)
    count = subprocess.check_output(
        ["git", "-C", str(layout.dot_dir), "rev-list", "--count", "HEAD"], text=True,
    )
    assert int(count) == 3
    assert subprocess.check_output(
        ["git", "-C", str(layout.dot_dir), "status", "--porcelain"], text=True,
    ) == ""
    assert LOCK_NAME not in export_bundle(layout).model_dump_json()
    assert not (layout.dot_dir / LOCK_NAME).exists()


def test_threads_and_symlink_alias_share_lock(tmp_path: Path) -> None:
    root = tmp_path / "project"
    layout = init_project(root, with_scaffold=False).layout
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    started = threading.Event()

    def commit() -> int:
        started.set()
        return apply_patch_now(
            ProjectLayout(alias), actor="thread",
            ops=[CreateNodeOp(type="directory", name="thread")],
        ).graph_version

    with ThreadPoolExecutor(max_workers=1) as pool:
        with project_write_lock(root):
            pending = pool.submit(commit)
            assert started.wait(5)
            assert not pending.done()
            # This nested call must not block on our own file lock.
            assert apply_patch_now(
                layout, actor="main", ops=[CreateNodeOp(type="directory", name="main")],
            ).graph_version == 1
        assert pending.result(timeout=10) == 2
    _healthy(layout, 2)


def test_other_project_writes_while_lock_held(
    tmp_path: Path, writer: Callable[..., Process],
) -> None:
    first = init_project(tmp_path / "first", with_scaffold=False).layout
    second = init_project(tmp_path / "second", with_scaffold=False).layout
    with project_write_lock(first.root):
        assert _result(writer(second.root, "now")) == 1
    _healthy(first, 0)
    _healthy(second, 1)


def test_failed_lock_and_invalid_commit_release_without_writing(
    tmp_path: Path, writer: Callable[..., Process], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from simulanka.kernel.validator import ValidationError
    from simulanka.storage import write_lock

    layout = init_project(tmp_path, with_scaffold=False).layout
    before = layout.manifest_path.read_bytes()

    def fail(_fd: int) -> None:
        raise PermissionError("lock unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(write_lock, "_acquire", fail)
        with pytest.raises(PermissionError, match="lock unavailable"):
            apply_patch_now(layout, actor="test", ops=[CreateNodeOp(type="directory", name="x")])
    with pytest.raises(ValidationError):
        apply_patch_now(layout, actor="test", ops=[CreateNodeOp(type="not-a-profile", name="x")])
    assert layout.manifest_path.read_bytes() == before
    assert not list(iter_nodes(layout))
    assert not list(iter_events(layout))
    assert _result(writer(tmp_path, "now", "after")) == 1


def test_dead_owner_does_not_leave_stale_lock(
    tmp_path: Path, writer: Callable[..., Process],
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    owner = writer(tmp_path, "hold")
    assert _line(owner) == "inside"
    waiter = writer(tmp_path, "now", "after", "lock")
    assert _line(waiter) == "attempt"
    _blocked(waiter)
    owner.kill()
    owner.wait(timeout=10)
    assert _result(waiter) == 1
    assert (tmp_path / LOCK_NAME).exists()
    _healthy(layout, 1)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork only")
def test_fork_does_not_inherit_reentry_or_unlock_parent(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    read_fd, write_fd = os.pipe()
    child = -1
    try:
        with project_write_lock(tmp_path):
            child = os.fork()
            if child == 0:
                os.close(read_fd)
                os.write(write_fd, b"ready")
                try:
                    with project_write_lock(tmp_path):
                        os.write(write_fd, b"inside")
                finally:
                    os._exit(0)
            os.close(write_fd)
            assert os.read(read_fd, 5) == b"ready"
            with selectors.DefaultSelector() as selector:
                selector.register(read_fd, selectors.EVENT_READ)
                assert not selector.select(0.15)
        with selectors.DefaultSelector() as selector:
            selector.register(read_fd, selectors.EVENT_READ)
            assert selector.select(10)
        assert os.read(read_fd, 6) == b"inside"
        assert os.waitpid(child, 0)[1] == 0
        child = -1
    finally:
        os.close(read_fd)
        if child > 0:
            import signal

            os.kill(child, signal.SIGKILL)
            os.waitpid(child, 0)
    _healthy(layout, 0)


def test_init_import_migrate_and_checkpoint_obey_project_lock(
    tmp_path: Path, writer: Callable[..., Process],
) -> None:
    from simulanka.kernel.bundle import write_bundle

    source = init_project(tmp_path / "source", with_scaffold=False).layout
    bundle_path = tmp_path / "bundle.json"
    write_bundle(export_bundle(source), bundle_path)
    # Root exists before the lock; neither maintenance entry may create its
    # graph directory or decide that an import target is empty outside it.
    target = tmp_path / "target"
    target.mkdir()
    with project_write_lock(target):
        importer = writer(target, "import", str(bundle_path), "lock")
        assert _line(importer) == "attempt"
        _blocked(importer)
        assert not (target / ".simulanka").exists()
        init_project(target, with_scaffold=False)
    assert _result(importer)["error"] == "ImportTargetNotEmpty"

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    with project_write_lock(fresh):
        initializer = writer(fresh, "init", gate="lock")
        assert _line(initializer) == "attempt"
        _blocked(initializer)
        init_project(fresh)
    assert _result(initializer) == "already_initialized"

    layout = ProjectLayout(target)
    write_manifest(layout, layout.load_manifest().model_copy(update={"registry_version": 1}))
    with project_write_lock(target):
        migrators = [writer(target, "migrate", gate="lock") for _ in range(2)]
        for proc in migrators:
            assert _line(proc) == "attempt"
            _blocked(proc)
    assert sorted(_result(proc) for proc in migrators) == [0, 1]
    _healthy(layout, 1)
    with project_write_lock(target):
        checkpointer = writer(target, "checkpoint", gate="lock")
        assert _line(checkpointer) == "attempt"
        _blocked(checkpointer)
    # ensure_repo and checkpoint acquire separately.
    assert _line(checkpointer) == "attempt"
    assert _result(checkpointer) is False


def test_waiting_agent_preserves_new_human_verdict(
    tmp_path: Path, writer: Callable[..., Process],
) -> None:
    from tests.test_server import _seed_ghost_edge, _seed_project

    layout = _seed_project(tmp_path)
    edge_id = _seed_ghost_edge(layout)
    with project_write_lock(tmp_path):
        agent = writer(tmp_path, "agent_verdict", edge_id, "lock")
        assert _line(agent) == "attempt"
        _blocked(agent)
        apply_patch_now(layout, actor="user", ops=[UpdateAttrsOp(
            target=edge_id, attrs={"verdict": "correct", "verdict_by": "user"},
        )])
    outcome = _result(agent)
    assert outcome["applied"] == []
    assert "human verdict stands" in outcome["rejected"][0]["reason"]


def test_http_keep_rechecks_state_after_library_commit(
    tmp_path: Path, writer: Callable[..., Process],
) -> None:
    from simulanka.storage.entity_store import load_edge
    from tests.test_server import _seed_ghost_edge, _seed_project

    layout = _seed_project(tmp_path)
    edge_id = _seed_ghost_edge(layout)
    request = writer(tmp_path, "accept", edge_id, "lock", go=False)
    with project_write_lock(tmp_path):
        _send(request, "go")
        assert _line(request) == "attempt"
        _blocked(request)
        receipt = apply_patch_now(layout, actor="user", ops=[UpdateAttrsOp(
            target=edge_id,
            attrs={"status": "accepted", "verdict": "correct", "verdict_by": "user"},
        )])
    outcome = _result(request)
    assert outcome["status"] == 422
    assert "only a proposed ghost" in outcome["body"]["detail"]
    assert layout.load_manifest().graph_version == receipt.graph_version
    assert load_edge(layout, edge_id).attrs["status"] == "accepted"
    _healthy(layout, receipt.graph_version)
