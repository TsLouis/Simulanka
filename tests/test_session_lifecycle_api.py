from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException

from simulanka.agent.session import SessionEvent
from simulanka.layout import init_project
from simulanka.server.app import create_app
from simulanka.server.sessions import (
    append_session_event,
    archive_session,
    create_session,
    fork_session,
    list_sessions,
    load_session,
    read_session_events,
)


def test_list_fork_and_archive_are_durable_and_non_destructive(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    parent = create_session(
        layout,
        provider_id="codex",
        model="gpt-parent",
        workspace="workspace",
    )
    append_session_event(
        layout,
        parent.session_id,
        SessionEvent(
            type="status",
            status="done",
            provider_session_id="thread-parent",
        ),
    )

    child = fork_session(
        layout,
        parent.session_id,
        provider_id="opencode",
        model=None,
        inherit_model=False,
        forked_from_event_id="event-7",
    )

    assert child.provider_id == "opencode"
    assert child.model is None
    assert child.native_session_id is None
    assert child.workspace == str((tmp_path / "workspace").resolve())
    assert child.parent_session_id == parent.session_id
    assert child.forked_from_event_id == "event-7"
    assert len(read_session_events(layout, child.session_id)) == 1
    assert {state.session_id for state in list_sessions(layout)} == {
        parent.session_id,
        child.session_id,
    }

    before_parent = read_session_events(layout, parent.session_id)
    archived = archive_session(layout, child.session_id)
    assert archived.status == "archived"
    event_count = len(read_session_events(layout, child.session_id))
    assert archive_session(layout, child.session_id).status == "archived"
    assert len(read_session_events(layout, child.session_id)) == event_count
    assert read_session_events(layout, parent.session_id) == before_parent


def test_session_lifecycle_routes_enforce_binding_and_archived_read_only(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    parent = create_session(layout, provider_id="codex", model="gpt-parent")
    app = create_app(layout)
    list_route = _endpoint(app, "/session", "GET")
    history_route = _endpoint(app, "/session/{session_id}/history", "GET")
    fork_route = _endpoint(app, "/session/{session_id}/fork", "POST")
    archive_route = _endpoint(app, "/session/{session_id}/archive", "POST")
    message_route = _endpoint(app, "/session/{session_id}/message", "POST")

    child = fork_route(
        parent.session_id,
        {
            "provider_id": "opencode",
            "model": None,
            "forked_from_event_id": "event-3",
        },
    )
    assert child["provider_id"] == "opencode"
    assert child["model"] is None
    assert child["parent_session_id"] == parent.session_id
    assert child["forked_from_event_id"] == "event-3"
    assert load_session(layout, parent.session_id).provider_id == "codex"
    assert load_session(layout, parent.session_id).model == "gpt-parent"

    listed = list_route()
    assert {record["session_id"] for record in listed["sessions"]} == {
        parent.session_id,
        child["session_id"],
    }
    history = history_route(child["session_id"])
    assert history["session"] == child
    assert history["events"][0]["status"] == "created"

    archived = archive_route(child["session_id"], {})
    assert archived["status"] == "archived"
    assert archive_route(child["session_id"], {}) == archived
    with pytest.raises(HTTPException) as read_only:
        message_route(child["session_id"], {"text": "resume"})
    assert read_only.value.status_code == 409

    count_before = len(list_route()["sessions"])
    with pytest.raises(HTTPException) as unknown_provider:
        fork_route(parent.session_id, {"provider_id": "missing"})
    assert unknown_provider.value.status_code == 422
    assert len(list_route()["sessions"]) == count_before

    append_session_event(
        layout,
        parent.session_id,
        SessionEvent(type="status", status="running"),
    )
    with pytest.raises(HTTPException) as running:
        archive_route(parent.session_id, {})
    assert running.value.status_code == 409


def test_corrupt_session_state_is_reported_as_conflict(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    parent = create_session(layout, provider_id="codex")
    append_session_event(
        layout,
        parent.session_id,
        SessionEvent(type="status", provider_session_id="thread-one"),
    )
    append_session_event(
        layout,
        parent.session_id,
        SessionEvent(type="status", provider_session_id="thread-two"),
    )
    app = create_app(layout)
    history_route = _endpoint(app, "/session/{session_id}/history", "GET")
    fork_route = _endpoint(app, "/session/{session_id}/fork", "POST")

    with pytest.raises(HTTPException) as history_conflict:
        history_route(parent.session_id)
    assert history_conflict.value.status_code == 409
    with pytest.raises(HTTPException) as fork_conflict:
        fork_route(parent.session_id, {})
    assert fork_conflict.value.status_code == 409


def _endpoint(app: FastAPI, path: str, method: str) -> Callable[..., Any]:
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(
            route,
            "methods",
            set(),
        ):
            endpoint = getattr(route, "endpoint", None)
            if callable(endpoint):
                return cast(Callable[..., Any], endpoint)
    raise AssertionError(f"no {method} {path} route")
