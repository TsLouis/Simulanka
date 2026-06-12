"""opencode session harness for the verify-discuss loop.

The server/frontend write path belongs to Claude's side of the split. This
module is the Codex side: continue an opencode session non-interactively,
extract the assistant text from ``--format json`` output, and parse structured
operation blocks that a server can later filter and apply.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TIMEOUT = 180.0

CommandRunner = Callable[[list[str], float], str]


class HarnessError(RuntimeError):
    """Raised when the opencode harness cannot run or parse enough output."""


@dataclass(frozen=True)
class DiscussionOp:
    """One proposed graph-side operation emitted by the discussion agent.

    This is intentionally generic. The harness parses intent; the server owns
    permission checks and translation to kernel ops.
    """

    op: str
    attrs: dict[str, Any] = field(default_factory=dict)
    edge_id: str | None = None
    source: str | None = None
    target: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpBlockResult:
    ops: list[DiscussionOp]
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OpenCodeTurn:
    """Parsed result of one non-interactive opencode turn."""

    session_id: str | None
    text: str
    ops: list[DiscussionOp]
    op_errors: list[str]
    events: list[dict[str, Any]]
    raw: str


def run_opencode_turn(
    message: str,
    *,
    session_id: str | None = None,
    model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    runner: CommandRunner | None = None,
) -> OpenCodeTurn:
    """Run one opencode turn and parse assistant text + structured op blocks."""
    if not message.strip():
        raise HarnessError("message must be non-empty.")

    args = ["opencode", "run", "--print-logs", "--format", "json"]
    if model:
        args.extend(["-m", model])
    if session_id:
        args.extend(["-s", session_id])
    args.append(message)

    raw = runner(args, timeout) if runner is not None else _run_command(args, timeout)
    events = parse_json_events(raw)
    text = assistant_text(events) or raw.strip()
    parsed = parse_op_blocks(text)
    return OpenCodeTurn(
        session_id=session_id_from_events(events) or session_id,
        text=text,
        ops=parsed.ops,
        op_errors=parsed.errors,
        events=events,
        raw=raw,
    )


def parse_json_events(raw: str) -> list[dict[str, Any]]:
    """Parse opencode ``--format json`` output.

    Current opencode emits raw JSON events. Accept JSONL, a JSON array, or a
    single JSON object so version drift does not break the harness immediately.
    """
    stripped = raw.strip()
    if not stripped:
        return []

    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        return [value]

    events: list[dict[str, Any]] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def assistant_text(events: list[dict[str, Any]]) -> str:
    """Best-effort assistant text extraction from opencode JSON events."""
    chunks: list[str] = []
    for event in events:
        role = _role(event)
        if role is not None and role != "assistant":
            continue
        text = _text_from_value(event)
        if text:
            chunks.append(text)
    return "\n".join(_dedupe_adjacent(chunks)).strip()


def session_id_from_events(events: list[dict[str, Any]]) -> str | None:
    """Find the session id in common opencode event shapes."""
    for event in events:
        for key in ("sessionID", "session_id", "sessionId"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        session = event.get("session")
        if isinstance(session, dict):
            value = session.get("id")
            if isinstance(value, str) and value:
                return value
    return None


def parse_op_blocks(text: str) -> OpBlockResult:
    """Parse fenced ``simulanka-ops`` JSON blocks from assistant text."""
    ops: list[DiscussionOp] = []
    errors: list[str] = []
    for body in _fenced_blocks(text, "simulanka-ops"):
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid simulanka-ops JSON: {exc.msg}")
            continue
        raw_ops = payload.get("ops") if isinstance(payload, dict) else payload
        if not isinstance(raw_ops, list):
            errors.append("simulanka-ops block must be a JSON list or {\"ops\": [...]}.")
            continue
        for i, item in enumerate(raw_ops):
            try:
                ops.append(_coerce_op(item))
            except ValueError as exc:
                errors.append(f"op[{i}]: {exc}")
    return OpBlockResult(ops=ops, errors=errors)


def _run_command(args: list[str], timeout: float) -> str:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HarnessError("`opencode` CLI not found on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise HarnessError(f"opencode timed out after {timeout}s.") from exc
    if proc.returncode != 0:
        raise HarnessError(
            f"opencode exited {proc.returncode}: {proc.stderr.strip()[:500]}"
        )
    return proc.stdout


def _coerce_op(item: object) -> DiscussionOp:
    if not isinstance(item, dict):
        raise ValueError("expected object")
    op = item.get("op") or item.get("kind")
    if not isinstance(op, str) or not op:
        raise ValueError("missing string `op`")
    attrs = item.get("attrs", {})
    if not isinstance(attrs, dict):
        raise ValueError("`attrs` must be an object when present")
    edge_id = _optional_str(item, "edge_id") or _optional_str(item, "edge")
    source = _optional_str(item, "source")
    target = _optional_str(item, "target")
    return DiscussionOp(
        op=op,
        edge_id=edge_id,
        source=source,
        target=target,
        attrs=dict(attrs),
        raw=dict(item),
    )


def _optional_str(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    return value if isinstance(value, str) and value else None


def _fenced_blocks(text: str, label: str) -> Iterator[str]:
    fence = "```"
    pos = 0
    while True:
        start = text.find(fence, pos)
        if start == -1:
            return
        line_end = text.find("\n", start + len(fence))
        if line_end == -1:
            return
        info = text[start + len(fence):line_end].strip().lower()
        end = text.find(fence, line_end + 1)
        if end == -1:
            return
        if info == label:
            yield text[line_end + 1:end].strip()
        pos = end + len(fence)


def _role(event: dict[str, Any]) -> str | None:
    role = event.get("role")
    if isinstance(role, str):
        return role
    message = event.get("message")
    if isinstance(message, dict):
        nested = message.get("role")
        if isinstance(nested, str):
            return nested
    return None


def _text_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "delta", "content"):
            text = _text_from_value(value.get(key))
            if text:
                return text
        message = value.get("message")
        text = _text_from_value(message)
        if text:
            return text
        parts = value.get("parts")
        text = _text_from_value(parts)
        if text:
            return text
    if isinstance(value, list):
        chunks = [_text_from_value(x) for x in value]
        return "".join(chunks)
    return ""


def _dedupe_adjacent(chunks: list[str]) -> Iterator[str]:
    previous: str | None = None
    for chunk in chunks:
        if chunk == previous:
            continue
        previous = chunk
        yield chunk
