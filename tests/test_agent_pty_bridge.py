from __future__ import annotations

import sys
import time

import pytest

from simulanka.agent.pty_bridge import (
    PtyAgentSession,
    PtyBridgeError,
    PtySemanticSidecar,
)


def _read_until(session: PtyAgentSession, needle: str, *, timeout: float = 3.0) -> str:
    deadline = time.monotonic() + timeout
    seen = ""
    while time.monotonic() < deadline:
        update = session.read(timeout=0.05)
        if update.semantic.text:
            seen += update.semantic.text
        if needle in seen:
            return seen
        if update.exited and not update.data:
            break
    raise AssertionError(f"did not see {needle!r}; saw {seen!r}")


def test_sidecar_strips_ansi_and_keeps_transcript() -> None:
    sidecar = PtySemanticSidecar(transcript_limit=20)

    update = sidecar.feed(b"\x1b[31mred\x1b[0m\r\nplain")

    assert update.text == "red\nplain"
    assert sidecar.transcript == "red\nplain"


def test_sidecar_extracts_split_simulanka_ops_once() -> None:
    sidecar = PtySemanticSidecar()

    first = sidecar.feed(
        b"thinking\n```simulanka-ops\n"
        b'[{"op": "update_edge_attrs", "edge_id": "edg_1",'
    )
    second = sidecar.feed(b' "attrs": {"verdict": "correct"}}]\n```\nmore')
    third = sidecar.feed(b"\nno duplicate")

    assert first.ops == []
    assert len(second.ops) == 1
    assert second.ops[0].op == "update_edge_attrs"
    assert second.ops[0].edge_id == "edg_1"
    assert second.ops[0].attrs == {"verdict": "correct"}
    assert second.op_errors == []
    assert third.ops == []


def test_sidecar_reports_op_errors() -> None:
    sidecar = PtySemanticSidecar()

    update = sidecar.feed(b"```simulanka-ops\n{\"ops\": [{\"op\": \"bad\", \"attrs\": []}]}\n```")

    assert update.ops == []
    assert update.op_errors == ["op[0]: `attrs` must be an object when present"]


def test_pty_agent_session_round_trips_input() -> None:
    script = (
        "import sys; "
        "print('ready', flush=True); "
        "line = sys.stdin.readline(); "
        "print('got:' + line.strip(), flush=True)"
    )

    session = PtyAgentSession([sys.executable, "-c", script], rows=24, cols=80)
    try:
        assert "ready" in _read_until(session, "ready")
        session.send_line("hello")
        assert "got:hello" in _read_until(session, "got:hello")
    finally:
        session.terminate()


def test_pty_agent_session_rejects_bad_shape() -> None:
    with pytest.raises(PtyBridgeError):
        PtyAgentSession([])
