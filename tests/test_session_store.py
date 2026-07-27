from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulanka.agent.session import SessionEvent
from simulanka.layout import init_project
from simulanka.server.sessions import (
    SessionStateError,
    append_session_event,
    create_session,
    load_session,
    load_work_session,
)


def test_generic_session_persists_creation_binding_and_recovers_runtime_state(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    created = create_session(
        layout,
        provider_id="  codex  ",
        model="  gpt-5.6  ",
        workspace="workspace",
        parent_session_id="ses_01ARZ3NDEKTSV4RRFFQ69G5FAV",
        forked_from_event_id="evt_42",
    )
    append_session_event(
        layout,
        created.session_id,
        SessionEvent(type="status", status="running", provider_session_id="thread-1"),
    )
    append_session_event(
        layout,
        created.session_id,
        SessionEvent(
            type="status",
            status="done",
            details={"provider_id": "opencode", "model": "other-model"},
        ),
    )

    loaded = load_session(layout, created.session_id)
    assert loaded.provider_id == "codex"
    assert loaded.model == "gpt-5.6"
    assert loaded.native_session_id == "thread-1"
    assert loaded.workspace == str((tmp_path / "workspace").resolve())
    assert loaded.parent_session_id == "ses_01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert loaded.forked_from_event_id == "evt_42"
    assert loaded.status == "done"
    assert loaded.turn_running is False
    assert loaded.legacy_anchor is None


def test_legacy_jsonl_defaults_provider_and_workspace_and_compatibility_facade(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    legacy_id = "ses_01ARZ3NDEKTSV4RRFFQ69G5FAV"
    legacy_path = layout.dot_dir / "agent" / "sessions" / f"{legacy_id}.jsonl"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(
        json.dumps(
            {
                "type": "status",
                "status": "created",
                "details": {
                    "session_id": legacy_id,
                    "anchor": {"id": "nod_task", "name": "legacy task"},
                    "model": "legacy-model",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    append_session_event(
        layout,
        legacy_id,
        SessionEvent(type="status", status="running", provider_session_id="old-native"),
    )

    loaded = load_session(layout, legacy_id)
    compat = load_work_session(layout, legacy_id)
    assert loaded.provider_id == "opencode"
    assert loaded.workspace == str(layout.root)
    assert loaded.legacy_anchor == {"id": "nod_task", "name": "legacy task"}
    assert loaded.native_session_id == "old-native"
    assert loaded.status == "running"
    assert compat.anchor == loaded.legacy_anchor
    assert compat.provider_session_id == "old-native"
    assert compat.turn_running is True


def test_only_lifecycle_events_update_session_status(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    created = create_session(layout, provider_id="opencode")
    for event in (
        SessionEvent(type="status", status="running"),
        SessionEvent(type="tool_call", status="completed"),
        SessionEvent(type="tool_result", status="failed"),
        SessionEvent(type="status", status="step_done"),
        SessionEvent(type="status", status="event"),
    ):
        append_session_event(layout, created.session_id, event)

    assert load_session(layout, created.session_id).status == "running"
    append_session_event(
        layout,
        created.session_id,
        SessionEvent(type="status", status="completed"),
    )
    assert load_session(layout, created.session_id).status == "done"
    append_session_event(layout, created.session_id, SessionEvent(type="error"))
    assert load_session(layout, created.session_id).status == "failed"


def test_native_session_id_binding_allows_repeats_and_rejects_changes(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    created = create_session(layout, provider_id="opencode")
    append_session_event(
        layout,
        created.session_id,
        SessionEvent(type="agent_text", provider_session_id="native-1"),
    )
    append_session_event(
        layout,
        created.session_id,
        SessionEvent(type="status", status="running", provider_session_id="native-1"),
    )
    assert load_session(layout, created.session_id).native_session_id == "native-1"

    append_session_event(
        layout,
        created.session_id,
        SessionEvent(type="agent_text", provider_session_id="native-2"),
    )
    with pytest.raises(SessionStateError, match="changed native session id"):
        load_session(layout, created.session_id)


def test_created_native_session_id_cannot_be_rebound(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    session_id = "ses_01ARZ3NDEKTSV4RRFFQ69G5FAV"
    path = layout.dot_dir / "agent" / "sessions" / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "status",
                "status": "created",
                "details": {
                    "session_id": session_id,
                    "provider_id": "opencode",
                    "native_session_id": "created-native",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    append_session_event(
        layout,
        session_id,
        SessionEvent(type="agent_text", provider_session_id="other-native"),
    )

    with pytest.raises(SessionStateError, match="created-native"):
        load_session(layout, session_id)
