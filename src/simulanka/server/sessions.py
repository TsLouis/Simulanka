"""Disk-backed state for embedded agent sessions."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ulid import ULID

from simulanka.agent.context import (
    ContextBundle,
    compose_message,
    decide_context_delivery,
    mark_context_sent,
    store_context_bundle,
)
from simulanka.agent.session import (
    SessionEvent,
    StreamRunner,
    provider_adapters,
    stream_opencode_events,
)
from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Node

_SESSION_ID_RE = re.compile(r"^ses_[0-9A-HJKMNP-TV-Z]{26}$")

SessionStatus = Literal[
    "idle",
    "running",
    "done",
    "failed",
    "interrupted",
    "orphaned",
    "native_missing",
    "stateless",
    "archived",
]
ScopeStatus = Literal["bound", "unassigned", "missing", "broken"]

_LIFECYCLE_STATUSES: dict[str, SessionStatus] = {
    "idle": "idle",
    "running": "running",
    "done": "done",
    "completed": "done",
    "failed": "failed",
    "interrupted": "interrupted",
    "orphaned": "orphaned",
    "native_missing": "native_missing",
    "stateless": "stateless",
    "archived": "archived",
}


class SessionNotFound(ValueError):
    """Raised when an embedded session does not exist."""


class SessionStateError(ValueError):
    """Raised when persisted events violate a session binding invariant."""


@dataclass(frozen=True)
class Session:
    """Durable, provider-neutral description of one agent session."""

    session_id: str
    provider_id: str
    model: str | None
    native_session_id: str | None
    workspace: str
    parent_session_id: str | None
    forked_from_event_id: str | None
    status: SessionStatus
    scope_root_id: str | None = None
    scope_defined: bool = False
    legacy_anchor: dict[str, Any] | None = None

    @property
    def provider_session_id(self) -> str | None:
        """Compatibility alias for the old OpenCode-specific field."""
        return self.native_session_id

    @property
    def turn_running(self) -> bool:
        """Compatibility view consumed by the pre-migration server routes."""
        return self.status == "running"


@dataclass(frozen=True)
class WorkSession:
    """Compatibility facade for task-anchored callers during the migration."""

    session_id: str
    anchor: dict[str, Any] | None
    model: str | None
    provider_session_id: str | None
    turn_running: bool


@dataclass(frozen=True)
class SessionTreeBinding:
    """UI-sidecar placement projected from a Session parent forest."""

    tree_id: str
    scope_root_id: str | None
    scope_status: ScopeStatus


def create_session(
    layout: ProjectLayout,
    *,
    provider_id: str,
    model: str | None = None,
    workspace: str | Path | None = None,
    parent_session_id: str | None = None,
    forked_from_event_id: str | None = None,
    scope_root_id: str | None = None,
) -> Session:
    """Create a generic root Session in an explicit graph-view scope."""
    return _create_session(
        layout,
        provider_id=provider_id,
        model=model,
        workspace=workspace,
        parent_session_id=parent_session_id,
        forked_from_event_id=forked_from_event_id,
        scope_root_id=scope_root_id,
        scope_defined=parent_session_id is None,
        legacy_anchor=None,
    )


def _create_session(
    layout: ProjectLayout,
    *,
    provider_id: str,
    model: str | None,
    workspace: str | Path | None,
    parent_session_id: str | None,
    forked_from_event_id: str | None,
    scope_root_id: str | None,
    scope_defined: bool,
    legacy_anchor: dict[str, Any] | None,
) -> Session:
    provider_id = provider_id.strip()
    if not provider_id:
        raise ValueError("provider_id must be non-empty")
    if model is not None:
        model = model.strip()
        if not model:
            raise ValueError("model must be non-empty when provided")
    if parent_session_id is not None and not _SESSION_ID_RE.fullmatch(parent_session_id):
        raise ValueError("parent_session_id must be a valid session id")
    if forked_from_event_id is not None and not forked_from_event_id.strip():
        raise ValueError("forked_from_event_id must be non-empty when provided")
    if scope_root_id is not None:
        scope_root_id = scope_root_id.strip()
        if not scope_root_id:
            raise ValueError("scope_root_id must be non-empty when provided")

    session_id = f"ses_{ULID()}"
    workspace_value = _workspace_value(layout, workspace)
    details: dict[str, Any] = {
        "session_id": session_id,
        "provider_id": provider_id,
        "native_session_id": None,
        "workspace": workspace_value,
        "model": model,
        "parent_session_id": parent_session_id,
        "forked_from_event_id": forked_from_event_id,
        "status": "idle",
    }
    if scope_defined:
        # Explicit null means the project top-level view. Missing means a
        # pre-scope legacy Session or a fork that inherits from its parent.
        details["scope_root_id"] = scope_root_id
    if legacy_anchor is not None:
        # ``anchor`` keeps pre-S8 readers working; generic callers never write it.
        details["anchor"] = legacy_anchor
        details["legacy_anchor"] = legacy_anchor
    append_session_event(
        layout,
        session_id,
        SessionEvent(type="status", status="created", text="会话已创建", details=details),
    )
    return Session(
        session_id=session_id,
        provider_id=provider_id,
        model=model,
        native_session_id=None,
        workspace=workspace_value,
        parent_session_id=parent_session_id,
        forked_from_event_id=forked_from_event_id,
        status="idle",
        scope_root_id=scope_root_id if scope_defined else None,
        scope_defined=scope_defined,
        legacy_anchor=legacy_anchor,
    )


def create_work_session(
    layout: ProjectLayout,
    *,
    anchor: dict[str, Any] | None,
    model: str | None,
) -> WorkSession:
    state = _create_session(
        layout,
        provider_id="opencode",
        model=model,
        workspace=layout.root,
        parent_session_id=None,
        forked_from_event_id=None,
        scope_root_id=None,
        scope_defined=False,
        legacy_anchor=anchor,
    )
    return WorkSession(
        session_id=state.session_id,
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


def load_session(layout: ProjectLayout, session_id: str) -> Session:
    events = read_session_events(layout, session_id)
    if not events:
        raise SessionNotFound(f"session {session_id!r} has no state")
    created = events[0]
    details = created.get("details")
    if not isinstance(details, dict):
        raise SessionNotFound(f"session {session_id!r} has invalid state")
    provider_id = details.get("provider_id")
    if not isinstance(provider_id, str) or not provider_id:
        provider_id = "opencode"
    model = details.get("model")
    workspace = details.get("workspace")
    workspace_value = _workspace_value(
        layout,
        workspace if isinstance(workspace, str) and workspace else None,
    )
    parent_session_id = details.get("parent_session_id")
    if not isinstance(parent_session_id, str):
        parent_session_id = None
    forked_from_event_id = details.get("forked_from_event_id")
    if not isinstance(forked_from_event_id, str):
        forked_from_event_id = None
    scope_defined = "scope_root_id" in details
    scope_root_id = details.get("scope_root_id")
    if scope_root_id is not None and not isinstance(scope_root_id, str):
        raise SessionStateError(
            f"session {session_id!r} has invalid scope_root_id"
        )
    legacy_anchor = details.get("legacy_anchor", details.get("anchor"))
    native_session_id = details.get("native_session_id")
    if not isinstance(native_session_id, str) or not native_session_id:
        native_session_id = None
    status: SessionStatus = "idle"
    created_status = details.get("status")
    if isinstance(created_status, str):
        status = _LIFECYCLE_STATUSES.get(created_status, status)
    for event in events:
        candidate = event.get("provider_session_id")
        if isinstance(candidate, str) and candidate:
            if native_session_id is None:
                native_session_id = candidate
            elif native_session_id != candidate:
                raise SessionStateError(
                    f"session {session_id!r} changed native session id "
                    f"from {native_session_id!r} to {candidate!r}"
                )
        event_status = _lifecycle_status(event)
        if event_status is not None:
            status = event_status
    return Session(
        session_id=session_id,
        provider_id=provider_id,
        model=model if isinstance(model, str) else None,
        native_session_id=native_session_id,
        workspace=workspace_value,
        parent_session_id=parent_session_id,
        forked_from_event_id=forked_from_event_id,
        status=status,
        scope_root_id=scope_root_id,
        scope_defined=scope_defined,
        legacy_anchor=dict(legacy_anchor) if isinstance(legacy_anchor, dict) else None,
    )


def list_sessions(layout: ProjectLayout) -> list[Session]:
    """Scan durable JSONL sessions without maintaining a second index."""
    directory = layout.dot_dir / "agent" / "sessions"
    if not directory.is_dir():
        return []
    sessions: list[Session] = []
    for path in sorted(directory.glob("ses_*.jsonl"), reverse=True):
        try:
            sessions.append(load_session(layout, path.stem))
        except (SessionNotFound, SessionStateError):
            # A malformed sidecar must not hide every otherwise recoverable
            # session. Direct history access still reports the damaged id.
            continue
    return sessions


def session_tree_bindings(
    layout: ProjectLayout,
    sessions: Sequence[Session] | None = None,
) -> dict[str, SessionTreeBinding]:
    """Resolve tree identity and effective view scope without a second index."""
    states = list_sessions(layout) if sessions is None else list(sessions)
    by_id = {state.session_id: state for state in states}
    out: dict[str, SessionTreeBinding] = {}

    for state in states:
        cursor = state
        path: list[str] = []
        path_index: dict[str, int] = {}
        broken = False
        cycle_members: list[str] = []
        while cursor.parent_session_id is not None:
            cycle_start = path_index.get(cursor.session_id)
            if cycle_start is not None:
                broken = True
                cycle_members = path[cycle_start:]
                break
            path_index[cursor.session_id] = len(path)
            path.append(cursor.session_id)
            parent = by_id.get(cursor.parent_session_id)
            if parent is None:
                broken = True
                break
            cursor = parent

        if broken:
            # A missing-parent chain is grouped by its highest surviving
            # ancestor. A cycle has no root, so use the smallest member as a
            # deterministic recovery key shared by members and descendants.
            tree_id = (
                min(cycle_members)
                if cycle_members
                else cursor.session_id
            )
            out[state.session_id] = SessionTreeBinding(
                tree_id=tree_id,
                scope_root_id=None,
                scope_status="broken",
            )
            continue

        if not cursor.scope_defined:
            binding = SessionTreeBinding(
                tree_id=cursor.session_id,
                scope_root_id=None,
                scope_status="unassigned",
            )
        elif cursor.scope_root_id is None:
            binding = SessionTreeBinding(
                tree_id=cursor.session_id,
                scope_root_id=None,
                scope_status="bound",
            )
        else:
            binding = SessionTreeBinding(
                tree_id=cursor.session_id,
                scope_root_id=cursor.scope_root_id,
                scope_status=(
                    "bound"
                    if (layout.nodes_dir / f"{cursor.scope_root_id}.json").is_file()
                    else "missing"
                ),
            )
        out[state.session_id] = binding

    return out


def fork_session(
    layout: ProjectLayout,
    parent_session_id: str,
    *,
    provider_id: str | None = None,
    model: str | None = None,
    inherit_model: bool = True,
    forked_from_event_id: str | None = None,
) -> Session:
    """Create a blank child session; Provider history is never replayed."""
    parent = load_session(layout, parent_session_id)
    return _create_session(
        layout,
        provider_id=parent.provider_id if provider_id is None else provider_id,
        model=parent.model if inherit_model else model,
        workspace=parent.workspace,
        parent_session_id=parent.session_id,
        forked_from_event_id=forked_from_event_id,
        scope_root_id=None,
        scope_defined=False,
        legacy_anchor=None,
    )


def archive_session(layout: ProjectLayout, session_id: str) -> Session:
    """Archive a session non-destructively and idempotently."""
    state = load_session(layout, session_id)
    if state.status == "running":
        raise SessionStateError("cannot archive a running session")
    if state.status == "archived":
        return state
    append_session_event(
        layout,
        session_id,
        SessionEvent(type="status", status="archived", text="会话已归档"),
    )
    return load_session(layout, session_id)


def session_record(
    state: Session,
    binding: SessionTreeBinding | None = None,
) -> dict[str, Any]:
    """Return the stable provider-neutral API representation."""
    resolved = binding or SessionTreeBinding(
        tree_id=state.session_id,
        scope_root_id=state.scope_root_id,
        scope_status="bound" if state.scope_defined else "unassigned",
    )
    return {
        "session_id": state.session_id,
        "tree_id": resolved.tree_id,
        "scope_root_id": resolved.scope_root_id,
        "scope_status": resolved.scope_status,
        "provider_id": state.provider_id,
        "model": state.model,
        "native_session_id": state.native_session_id,
        "workspace": state.workspace,
        "parent_session_id": state.parent_session_id,
        "forked_from_event_id": state.forked_from_event_id,
        "status": state.status,
        "legacy": (
            state.legacy_anchor is not None
            or resolved.scope_status in {"unassigned", "broken"}
        ),
    }


def load_work_session(layout: ProjectLayout, session_id: str) -> WorkSession:
    """Load a generic Session through the old task-oriented shape."""
    state = load_session(layout, session_id)
    return WorkSession(
        session_id=state.session_id,
        anchor=state.legacy_anchor,
        model=state.model,
        provider_session_id=state.native_session_id,
        turn_running=state.turn_running,
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


def stream_session_turn(
    layout: ProjectLayout,
    state: Session,
    message: str,
    *,
    bundles: Sequence[ContextBundle] = (),
    runner: StreamRunner | None = None,
) -> Iterator[str]:
    """Run one provider-neutral turn without replaying transcript history."""

    def emit(event: SessionEvent) -> str:
        append_session_event(layout, state.session_id, event)
        return json.dumps(event.as_dict(), ensure_ascii=False) + "\n"

    terminal = False
    provider_events: Iterator[SessionEvent] | None = None
    try:
        send_bundles, context_details = _context_delivery_plan(layout, state, bundles)
        for bundle in send_bundles:
            store_context_bundle(layout, bundle)

        yield emit(
            SessionEvent(
                type="user_msg",
                text=message,
                details={"context_bundles": context_details} if context_details else {},
            )
        )
        yield emit(
            SessionEvent(
                type="status",
                status="running",
                text="请求已接收，agent 正在启动…",
            )
        )

        adapter = provider_adapters.create(
            state.provider_id,
            runner=runner,
            workspace=state.workspace,
        )
        if state.native_session_id is not None and not adapter.capabilities.native_resume:
            yield emit(
                SessionEvent(
                    type="status",
                    status="stateless",
                    text="当前 Provider 不支持原生续接；请新建会话",
                )
            )
            terminal = True
            return

        provider_message = compose_message(message, send_bundles)
        turn = (
            adapter.resume_turn(
                state.native_session_id,
                provider_message,
                model=state.model,
            )
            if state.native_session_id is not None
            else adapter.start_turn(provider_message, model=state.model)
        )
        provider_events = turn.events
        resolved_native_id = state.native_session_id
        provider_failed = False
        for event in provider_events:
            candidate = event.provider_session_id
            if candidate:
                if resolved_native_id is None:
                    resolved_native_id = candidate
                elif resolved_native_id != candidate:
                    raise SessionStateError(
                        f"session {state.session_id!r} changed native session id "
                        f"from {resolved_native_id!r} to {candidate!r}"
                    )
            provider_failed = provider_failed or event.type == "error" or (
                event.type == "status" and event.status == "failed"
            )
            yield emit(event)

        if provider_failed:
            yield emit(SessionEvent(type="status", status="failed", text="本轮失败"))
        elif adapter.capabilities.native_resume and resolved_native_id is None:
            yield emit(
                SessionEvent(
                    type="status",
                    status="native_missing",
                    text="Provider 未返回可续接的原生会话标识",
                )
            )
        elif not adapter.capabilities.native_resume:
            yield emit(
                SessionEvent(
                    type="status",
                    status="stateless",
                    text="本轮完成，但 Provider 不支持原生续接",
                )
            )
        else:
            assert resolved_native_id is not None
            for bundle in send_bundles:
                mark_context_sent(layout, resolved_native_id, bundle)
            yield emit(SessionEvent(type="status", status="done", text="本轮完成"))
        terminal = True
    except Exception as exc:
        yield emit(SessionEvent(type="error", status="failed", text=str(exc)))
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


def _context_delivery_plan(
    layout: ProjectLayout,
    state: Session,
    bundles: Sequence[ContextBundle],
) -> tuple[tuple[ContextBundle, ...], list[dict[str, str]]]:
    send: list[ContextBundle] = []
    details: list[dict[str, str]] = []
    seen: set[str] = set()
    for bundle in bundles:
        if bundle.digest in seen:
            continue
        seen.add(bundle.digest)
        payload = bundle.payload_object()
        if not payload.get("instruction") and not payload.get("reference"):
            decision, reason = "skip", "no_resolved_content"
        elif state.native_session_id is None:
            decision, reason = "send", "native_session_pending"
            send.append(bundle)
        else:
            delivery = decide_context_delivery(layout, state.native_session_id, bundle)
            decision = delivery.action
            reason = "already_sent" if decision == "skip" else "new_digest"
            if decision == "send":
                send.append(bundle)
        details.append(
            {
                "digest": bundle.digest,
                "decision": decision,
                "reason": reason,
            }
        )
    return tuple(send), details


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


def _workspace_value(layout: ProjectLayout, workspace: str | Path | None) -> str:
    path = layout.root if workspace is None else Path(workspace)
    if not path.is_absolute():
        path = layout.root / path
    return str(path.resolve())


def _lifecycle_status(event: dict[str, Any]) -> SessionStatus | None:
    if event.get("type") == "error":
        return "failed"
    if event.get("type") != "status":
        return None
    event_status = event.get("status")
    if not isinstance(event_status, str):
        return None
    return _LIFECYCLE_STATUSES.get(event_status)
