"""CLI-first wrapper around opencode with Simulanka sidecar recording."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import signal
import sys
import termios
import time
import tty
from collections.abc import Sequence
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, TextIO

from simulanka.agent.pty_bridge import PtyAgentSession, PtyRead

DEFAULT_OUTPUT_ROOT = Path(".simulanka/agent/opencode")


@dataclass(frozen=True)
class BridgePaths:
    run_dir: Path
    transcript: Path
    ops_jsonl: Path
    events_jsonl: Path


class JsonlRecorder(AbstractContextManager["JsonlRecorder"]):
    """Record semantic sidecar output while raw PTY bytes stay on the terminal."""

    def __init__(self, paths: BridgePaths) -> None:
        self.paths = paths
        self._transcript: TextIO | None = None
        self._ops: TextIO | None = None
        self._events: TextIO | None = None

    def __enter__(self) -> JsonlRecorder:
        self.paths.run_dir.mkdir(parents=True, exist_ok=True)
        self._transcript = self.paths.transcript.open("a", encoding="utf-8")
        self._ops = self.paths.ops_jsonl.open("a", encoding="utf-8")
        self._events = self.paths.events_jsonl.open("a", encoding="utf-8")
        self.event("bridge_start", {"run_dir": str(self.paths.run_dir)})
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.event("bridge_stop", {})
        for handle in (self._transcript, self._ops, self._events):
            if handle is not None:
                handle.close()

    def record_read(self, read: PtyRead) -> None:
        if read.semantic.text and self._transcript is not None:
            self._transcript.write(read.semantic.text)
            self._transcript.flush()
        for op in read.semantic.ops:
            self.op(op.raw)
        for error in read.semantic.op_errors:
            self.event("op_error", {"error": error})
        if read.exited:
            self.event("process_exit", {})

    def op(self, payload: dict[str, Any]) -> None:
        self._write_jsonl(self._ops, {"ts": time.time(), "op": payload})
        self.event("op", payload)

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        self._write_jsonl(self._events, {"ts": time.time(), "type": kind, "payload": payload})

    @staticmethod
    def _write_jsonl(handle: TextIO | None, payload: dict[str, Any]) -> None:
        if handle is None:
            return
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


class RawTerminal(AbstractContextManager["RawTerminal"]):
    """Temporarily put stdin in raw mode when running under a real terminal."""

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._attrs: list[Any] | None = None

    def __enter__(self) -> RawTerminal:
        if os.isatty(self._fd):
            self._attrs = termios.tcgetattr(self._fd)
            tty.setraw(self._fd)
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._attrs is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._attrs)


def build_paths(output_root: Path, *, name: str | None = None) -> BridgePaths:
    stamp = name or time.strftime("%Y%m%d-%H%M%S")
    run_dir = output_root / stamp
    return BridgePaths(
        run_dir=run_dir,
        transcript=run_dir / "transcript.txt",
        ops_jsonl=run_dir / "ops.jsonl",
        events_jsonl=run_dir / "events.jsonl",
    )


def build_opencode_argv(
    *,
    model: str | None = None,
    session_id: str | None = None,
    continue_last: bool = False,
    project: Path | None = None,
) -> list[str]:
    argv = ["opencode", "run", "--interactive"]
    if model:
        argv.extend(["-m", model])
    if session_id:
        argv.extend(["-s", session_id])
    if continue_last:
        argv.append("--continue")
    if project is not None:
        argv.extend(["--dir", str(project)])
    return argv


def run_bridge(
    *,
    cwd: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_name: str | None = None,
    model: str | None = None,
    session_id: str | None = None,
    continue_last: bool = False,
) -> int:
    """Run opencode in the current terminal while recording sidecar artifacts."""
    rows, cols = _terminal_size()
    paths = build_paths(output_root, name=run_name)
    argv = build_opencode_argv(
        model=model,
        session_id=session_id,
        continue_last=continue_last,
        project=cwd,
    )

    resize_pending = False

    def mark_resize(_signum: int, _frame: FrameType | None) -> None:
        nonlocal resize_pending
        resize_pending = True

    def consume_resize() -> bool:
        nonlocal resize_pending
        pending = resize_pending
        resize_pending = False
        return pending

    previous_sigwinch = signal.getsignal(signal.SIGWINCH)
    signal.signal(signal.SIGWINCH, mark_resize)

    try:
        with JsonlRecorder(paths) as recorder:
            _print_bridge_note(paths)
            with PtyAgentSession(argv, cwd=cwd, rows=rows, cols=cols) as session:
                return _pump_terminal(session, recorder, consume_resize)
    finally:
        signal.signal(signal.SIGWINCH, previous_sigwinch)


def _pump_terminal(
    session: PtyAgentSession,
    recorder: JsonlRecorder,
    resize_pending: Any,
) -> int:
    stdin_fd = sys.stdin.fileno()
    stdout = sys.stdout.buffer
    selector = selectors.DefaultSelector()
    selector.register(stdin_fd, selectors.EVENT_READ)

    try:
        with RawTerminal(stdin_fd):
            while True:
                if resize_pending():
                    rows, cols = _terminal_size()
                    session.resize(rows=rows, cols=cols)
                    recorder.event("resize", {"rows": rows, "cols": cols})

                read = session.read(timeout=0.01)
                if read.data:
                    stdout.write(read.data)
                    stdout.flush()
                recorder.record_read(read)

                if read.exited:
                    return session.returncode or 0

                for _key, _mask in selector.select(timeout=0):
                    data = os.read(stdin_fd, 65536)
                    if not data:
                        session.terminate()
                        return session.returncode or 0
                    session.write(data)
    except KeyboardInterrupt:
        session.interrupt()
        return 130
    finally:
        selector.close()


def _terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size(fallback=(120, 30))
    return size.lines, size.columns


def _print_bridge_note(paths: BridgePaths) -> None:
    note = (
        "\n[simulanka] opencode bridge recording:\n"
        f"  transcript: {paths.transcript}\n"
        f"  ops:        {paths.ops_jsonl}\n"
        f"  events:     {paths.events_jsonl}\n\n"
    )
    sys.stderr.write(note)
    sys.stderr.flush()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run opencode in a real terminal and record Simulanka sidecar events."
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Project directory for opencode.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where transcript and JSONL sidecar files are written.",
    )
    parser.add_argument("--run-name", help="Stable run directory name; defaults to a timestamp.")
    parser.add_argument("-m", "--model", help="opencode model, e.g. provider/model.")
    parser.add_argument(
        "-s",
        "--session",
        dest="session_id",
        help="opencode session id to continue.",
    )
    parser.add_argument(
        "-c",
        "--continue",
        dest="continue_last",
        action="store_true",
        help="Continue the latest opencode session.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    with suppress(BrokenPipeError):
        raise SystemExit(
            run_bridge(
                cwd=args.cwd.resolve(),
                output_root=args.output_root,
                run_name=args.run_name,
                model=args.model,
                session_id=args.session_id,
                continue_last=args.continue_last,
            )
        )


if __name__ == "__main__":
    main()
