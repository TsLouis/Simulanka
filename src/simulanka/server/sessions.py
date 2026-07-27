"""Disk-backed state for embedded agent sessions."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ulid import ULID

from simulanka.agent.session import (
    SessionEvent,
    StreamRunner,
    stream_opencode_events,
)
from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Node

_SESSION_ID_RE = re.compile(r"^ses_[0-9A-HJKMNP-TV-Z]{26}$")


class SessionNotFound(ValueError):
    """Raised when an embedded session does not exist."""


@dataclass(frozen=True)
class WorkSession:
    session_id: str
    anchor: dict[str, Any] | None
    model: str | None
    provider_session_id: str | None
    turn_running: bool


def create_work_session(
    layout: ProjectLayout,
    *,
    anchor: dict[str, Any] | None,
    model: str | None,
) -> WorkSession:
    session_id = f"ses_{ULID()}"
    event = SessionEvent(
        type="status",
        status="created",
        text="会话已创建",
        details={"session_id": session_id, "anchor": anchor, "model": model},
    )
    append_session_event(layout, session_id, event)
    return WorkSession(
        session_id=session_id,
        anchor=anchor,
        model=model,
        provider_session_id=None,
        turn_running=False,
    )


def append_session_event(
    layout: ProjectLayout,
    session_id: str,
    event: SessionEvent,
) -> None:
    path = _session_path(layout, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.as_dict(), ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def read_session_events(
    layout: ProjectLayout,
    session_id: str,
) -> list[dict[str, Any]]:
    path = _session_path(layout, session_id)
    if not path.is_file():
        raise SessionNotFound(f"session {session_id!r} not found")
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def load_work_session(layout: ProjectLayout, session_id: str) -> WorkSession:
    events = read_session_events(layout, session_id)
    if not events:
        raise SessionNotFound(f"session {session_id!r} has no state")
    created = events[0]
    details = created.get("details")
    if not isinstance(details, dict):
        raise SessionNotFound(f"session {session_id!r} has invalid state")
    anchor = details.get("anchor")
    model = details.get("model")
    provider_session_id: str | None = None
    turn_running = False
    for event in events:
        candidate = event.get("provider_session_id")
        if isinstance(candidate, str) and candidate:
            provider_session_id = candidate
        if event.get("type") == "status":
            status = event.get("status")
            if status == "running":
                turn_running = True
            elif status in {"done", "failed", "interrupted"}:
                turn_running = False
    return WorkSession(
        session_id=session_id,
        anchor=dict(anchor) if isinstance(anchor, dict) else None,
        model=model if isinstance(model, str) else None,
        provider_session_id=provider_session_id,
        turn_running=turn_running,
    )


def task_anchor(task: Node) -> dict[str, Any]:
    if task.type != "task":
        raise ValueError(f"node {task.id!r} is not a task")
    allowed = task.attrs.get("allowed_outputs")
    return {
        "id": task.id,
        "name": task.name,
        "goal": task.attrs.get("goal"),
        "allowed_outputs": list(allowed) if isinstance(allowed, list) else [],
        "acceptance_command": task.attrs.get("acceptance_command"),
    }


def render_first_message(state: WorkSession, message: str) -> str:
    if state.provider_session_id is not None or state.anchor is None:
        return message
    context = json.dumps(state.anchor, ensure_ascii=False, indent=2)
    return (
        "You are working from a Simulanka task card. Treat the following JSON "
        "as the exact task anchor; do not silently broaden it.\n\n"
        f"Task anchor:\n```json\n{context}\n```\n\n"
        f"Human message:\n{message}"
    )


def stream_work_session_turn(
    layout: ProjectLayout,
    state: WorkSession,
    message: str,
    *,
    runner: StreamRunner | None = None,
) -> Iterator[str]:
    """Yield persisted NDJSON for one turn, with exactly one terminal status."""

    def emit(event: SessionEvent) -> str:
        append_session_event(layout, state.session_id, event)
        return json.dumps(event.as_dict(), ensure_ascii=False) + "\n"

    terminal = False
    provider_events: Any = None
    provider_failed = False
    try:
        yield emit(SessionEvent(type="user_msg", text=message.strip()))
        yield emit(
            SessionEvent(
                type="status",
                status="running",
                text="请求已接收，agent 正在启动…",
            )
        )
        provider_events = stream_opencode_events(
            render_first_message(state, message.strip()),
            session_id=state.provider_session_id,
            model=state.model,
            runner=runner,
        )
        for event in provider_events:
            yield emit(event)
            provider_failed = provider_failed or event.type == "error"
        if provider_failed:
            yield emit(SessionEvent(type="status", status="failed", text="本轮失败"))
        else:
            yield emit(SessionEvent(type="status", status="done", text="本轮完成"))
        terminal = True
    except Exception as exc:
        yield emit(SessionEvent(type="error", text=str(exc)))
        yield emit(SessionEvent(type="status", status="failed", text="本轮失败"))
        terminal = True
    finally:
        if provider_events is not None:
            close = getattr(provider_events, "close", None)
            if callable(close):
                close()
        if not terminal:
            append_session_event(
                layout,
                state.session_id,
                SessionEvent(
                    type="status",
                    status="failed",
                    text="连接中断，本轮未完成",
                ),
            )


def _session_path(layout: ProjectLayout, session_id: str) -> Path:
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise SessionNotFound(f"invalid session id {session_id!r}")
    return layout.dot_dir / "agent" / "sessions" / f"{session_id}.jsonl"
