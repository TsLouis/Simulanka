"""PTY bridge for real-time agent sessions.

This module is intentionally UI-agnostic: a server can forward ``data`` bytes
to xterm.js while using the sidecar output to build transcripts and capture
structured Simulanka operation blocks.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import selectors
import signal
import struct
import subprocess
import termios
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from simulanka.agent.harness import DiscussionOp, parse_op_blocks

ANSI_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)

DEFAULT_READ_SIZE = 65536
DEFAULT_TRANSCRIPT_LIMIT = 200_000


class PtyBridgeError(RuntimeError):
    """Raised when a PTY session cannot be started or controlled."""


@dataclass(frozen=True)
class PtySemanticUpdate:
    """Semantic result from one chunk of terminal output."""

    text: str
    ops: list[DiscussionOp] = field(default_factory=list)
    op_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PtyRead:
    """One read from the PTY.

    ``data`` is the original byte stream for terminal rendering. ``semantic`` is
    derived from the same bytes and is safe for transcripts and op extraction.
    """

    data: bytes
    semantic: PtySemanticUpdate
    exited: bool


class PtySemanticSidecar:
    """Turn raw terminal bytes into transcript text and structured op blocks."""

    def __init__(self, *, transcript_limit: int = DEFAULT_TRANSCRIPT_LIMIT) -> None:
        if transcript_limit <= 0:
            raise ValueError("transcript_limit must be positive.")
        self._transcript_limit = transcript_limit
        self._transcript = ""
        self._pending_ops_text = ""

    @property
    def transcript(self) -> str:
        """Cleaned terminal transcript, bounded by ``transcript_limit``."""
        return self._transcript

    def feed(self, data: bytes) -> PtySemanticUpdate:
        """Consume one PTY chunk and return newly discovered semantic content."""
        text = _clean_terminal_text(data)
        if not text:
            return PtySemanticUpdate(text="")

        self._append_transcript(text)
        self._pending_ops_text += text

        op_texts, self._pending_ops_text = _pop_complete_op_blocks(self._pending_ops_text)
        ops: list[DiscussionOp] = []
        errors: list[str] = []
        for op_text in op_texts:
            parsed = parse_op_blocks(op_text)
            ops.extend(parsed.ops)
            errors.extend(parsed.errors)
        return PtySemanticUpdate(text=text, ops=ops, op_errors=errors)

    def _append_transcript(self, text: str) -> None:
        self._transcript += text
        if len(self._transcript) > self._transcript_limit:
            self._transcript = self._transcript[-self._transcript_limit :]


class PtyAgentSession:
    """A real-time PTY-backed agent process."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: dict[str, str] | None = None,
        rows: int = 30,
        cols: int = 120,
        sidecar: PtySemanticSidecar | None = None,
    ) -> None:
        if not argv:
            raise PtyBridgeError("argv must be non-empty.")

        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        self._selector = selectors.DefaultSelector()
        self._sidecar = sidecar or PtySemanticSidecar()
        self._closed = False

        try:
            _set_nonblocking(master_fd)
            _resize_fd(slave_fd, rows=rows, cols=cols)
            self._proc = subprocess.Popen(
                list(argv),
                cwd=os.fspath(cwd) if cwd is not None else None,
                env=env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                close_fds=True,
            )
        except Exception:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        finally:
            with suppress(OSError):
                os.close(slave_fd)

        self._selector.register(master_fd, selectors.EVENT_READ)

    @classmethod
    def opencode(
        cls,
        *,
        session_id: str | None = None,
        model: str | None = None,
        cwd: str | os.PathLike[str] | None = None,
        rows: int = 30,
        cols: int = 120,
    ) -> PtyAgentSession:
        """Create an interactive opencode session suitable for terminal streaming."""
        argv = ["opencode", "run", "--interactive"]
        if model:
            argv.extend(["-m", model])
        if session_id:
            argv.extend(["-s", session_id])
        return cls(argv, cwd=cwd, rows=rows, cols=cols)

    @property
    def pid(self) -> int:
        return self._proc.pid

    @property
    def returncode(self) -> int | None:
        return self._proc.poll()

    @property
    def transcript(self) -> str:
        return self._sidecar.transcript

    def write(self, data: str | bytes) -> None:
        """Write user input to the terminal."""
        payload = data.encode() if isinstance(data, str) else data
        if not payload:
            return
        self._write_all(payload)

    def send_line(self, line: str) -> None:
        """Write a line followed by enter."""
        self.write(line + "\n")

    def interrupt(self) -> None:
        """Send Ctrl-C to the child process group."""
        if self.returncode is not None:
            return
        os.killpg(self._proc.pid, signal.SIGINT)

    def resize(self, *, rows: int, cols: int) -> None:
        """Resize the PTY and notify terminal-aware programs."""
        _resize_fd(self._master_fd, rows=rows, cols=cols)
        if self.returncode is None:
            os.killpg(self._proc.pid, signal.SIGWINCH)

    def read(self, *, timeout: float = 0.05, max_bytes: int = DEFAULT_READ_SIZE) -> PtyRead:
        """Read currently available output without blocking past ``timeout``."""
        if self._closed:
            return PtyRead(data=b"", semantic=PtySemanticUpdate(text=""), exited=True)

        events = self._selector.select(timeout)
        if not events:
            return PtyRead(
                data=b"",
                semantic=PtySemanticUpdate(text=""),
                exited=self.returncode is not None,
            )

        chunks: list[bytes] = []
        while sum(len(chunk) for chunk in chunks) < max_bytes:
            try:
                chunk = os.read(self._master_fd, max_bytes)
            except BlockingIOError:
                break
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            chunks.append(chunk)

        data = b"".join(chunks)
        semantic = self._sidecar.feed(data)
        return PtyRead(data=data, semantic=semantic, exited=self.returncode is not None)

    def terminate(self, *, timeout: float = 2.0) -> None:
        """Terminate the child process group and close PTY resources."""
        if self.returncode is None:
            os.killpg(self._proc.pid, signal.SIGTERM)
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(self._proc.pid, signal.SIGKILL)
                self._proc.wait(timeout=timeout)
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with suppress(Exception):
            self._selector.unregister(self._master_fd)
        self._selector.close()
        os.close(self._master_fd)

    def __enter__(self) -> PtyAgentSession:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.terminate()

    def _write_all(self, data: bytes) -> None:
        total = 0
        while total < len(data):
            total += os.write(self._master_fd, data[total:])


def _clean_terminal_text(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    text = ANSI_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _pop_complete_op_blocks(text: str) -> tuple[list[str], str]:
    blocks: list[str] = []
    search_from = 0
    keep_from = 0
    fence = "```"
    label = "simulanka-ops"

    while True:
        start = text.find(fence, search_from)
        if start == -1:
            keep_from = max(0, len(text) - len(fence))
            break
        line_end = text.find("\n", start + len(fence))
        if line_end == -1:
            keep_from = start
            break

        info = text[start + len(fence) : line_end].strip().lower()
        end = text.find(fence, line_end + 1)
        if end == -1:
            keep_from = start
            break

        block_end = end + len(fence)
        if info == label:
            blocks.append(text[start:block_end])
        search_from = block_end
        keep_from = block_end

    return blocks, text[keep_from:]


def _set_nonblocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _resize_fd(fd: int, *, rows: int, cols: int) -> None:
    if rows <= 0 or cols <= 0:
        raise PtyBridgeError("rows and cols must be positive.")
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
