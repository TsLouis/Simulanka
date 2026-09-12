"""Cooperative project writes across threads and processes on a local filesystem.

The stable root sidecar must never be unlinked or replaced while writers run.
It deliberately lives outside the graph/checkpoint directory. Locking orders
writes; it does not provide crash recovery or a consistent snapshot to readers.
"""

from __future__ import annotations

import errno
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from weakref import WeakValueDictionary

LOCK_NAME = ".simulanka.write.lock"


@dataclass
class _State:
    gate: threading.RLock = field(default_factory=threading.RLock)
    depth: int = 0
    fd: int | None = None


_states: WeakValueDictionary[Path, _State] = WeakValueDictionary()
_registry_guard = threading.Lock()


def _after_fork() -> None:
    # Closing a child's inherited flock fd does not unlock the parent's open
    # file description. Explicit LOCK_UN here WOULD unlock the parent.
    global _states, _registry_guard
    for state in list(_states.values()):
        if state.fd is not None:
            os.close(state.fd)
            state.fd = None
    _states = WeakValueDictionary()
    _registry_guard = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


def _acquire(fd: int) -> None:
    if sys.platform == "win32":  # pragma: no cover - requires a Windows host
        import msvcrt

        # Windows can lock a byte beyond EOF, so the sidecar may stay empty.
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                time.sleep(0.05)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)


def _release(fd: int) -> None:
    if sys.platform == "win32":  # pragma: no cover - requires a Windows host
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def project_write_lock(root: Path) -> Iterator[None]:
    """Wait for this project's writer, reentering only on the owning thread.

    Callers create the project root before entering, but must do graph reads
    that decide a write *inside* this context. OS errors fail closed. Waiting
    has no artificial deadline; no Provider or external job belongs inside.
    """
    root = root.resolve()
    with _registry_guard:
        state = _states.get(root)
        if state is None:
            state = _State()
            _states[root] = state

    with state.gate:
        if state.depth:
            state.depth += 1
            try:
                yield
            finally:
                state.depth -= 1
            return

        pid = os.getpid()
        fd = os.open(root / LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o600)
        state.fd = fd  # Register before locking so fork cleanup can close it.
        try:
            _acquire(fd)
            state.depth = 1
            try:
                yield
            finally:
                state.depth = 0
                if os.getpid() == pid:
                    _release(fd)
        finally:
            if os.getpid() == pid:
                state.fd = None
                os.close(fd)
