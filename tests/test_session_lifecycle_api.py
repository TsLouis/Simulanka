from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException

from simulanka.agent.session import SessionEvent
from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateNodeOp
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.server.app import create_app
from simulanka.server.sessions import (
    append_session_event,
    archive_session,
    create_session,
    create_work_session,
    fork_session,
    list_sessions,
    load_session,
    read_session_events,
    session_tree_bindings,
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


def test_app_startup_recovers_running_session_once_as_orphaned(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    state = create_session(layout, provider_id="codex")
    append_session_event(
        layout,
        state.session_id,
        SessionEvent(
            type="status",
            status="running",
            provider_session_id="thread-orphaned",
        ),
    )

    app = create_app(layout)
    history_route = _endpoint(app, "/session/{session_id}/history", "GET")
    history = history_route(state.session_id)
    assert history["session"]["status"] == "orphaned"
    assert history["session"]["native_session_id"] == "thread-orphaned"
    assert history["events"][-1]["status"] == "orphaned"

    event_count = len(history["events"])
    create_app(layout)
    assert len(read_session_events(layout, state.session_id)) == event_count


def test_session_tree_scope_is_derived_across_multilevel_forks(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    scope_root_id = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="directory", name="scope")],
        actor="test",
    ).nodes[0]
    root = create_session(
        layout,
        provider_id="codex",
        scope_root_id=scope_root_id,
    )
    child = fork_session(layout, root.session_id)
    grandchild = fork_session(layout, child.session_id)

    states = list_sessions(layout)
    bindings = session_tree_bindings(layout, states)
    assert {
        (
            bindings[state.session_id].tree_id,
            bindings[state.session_id].scope_root_id,
            bindings[state.session_id].scope_status,
        )
        for state in states
    } == {(root.session_id, scope_root_id, "bound")}
    child_created = read_session_events(layout, child.session_id)[0]["details"]
    assert "scope_root_id" not in child_created

    list_route = _endpoint(create_app(layout), "/session", "GET")
    scoped = list_route(scope_root_id)
    assert {record["session_id"] for record in scoped["sessions"]} == {
        root.session_id,
        child.session_id,
        grandchild.session_id,
    }
    assert {record["tree_id"] for record in scoped["sessions"]} == {
        root.session_id
    }
    assert list_route("top") == {"sessions": []}
    assert list_route("unassigned") == {"sessions": []}


def test_scope_projection_separates_top_legacy_missing_and_broken_trees(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    top = create_session(layout, provider_id="codex")
    legacy = create_work_session(layout, anchor=None, model=None)
    missing = create_session(
        layout,
        provider_id="codex",
        scope_root_id="nod_missing",
    )
    missing_parent = "ses_01J00000000000000000000000"
    broken_root = create_session(
        layout,
        provider_id="codex",
        parent_session_id=missing_parent,
    )
    broken_child = fork_session(layout, broken_root.session_id)
    cycle_a = create_session(layout, provider_id="codex")
    cycle_b = create_session(layout, provider_id="codex")
    _rewrite_created_details(
        layout,
        cycle_a.session_id,
        parent_session_id=cycle_b.session_id,
    )
    _rewrite_created_details(
        layout,
        cycle_b.session_id,
        parent_session_id=cycle_a.session_id,
    )
    cycle_descendant = create_session(
        layout,
        provider_id="codex",
        parent_session_id=cycle_a.session_id,
    )

    bindings = session_tree_bindings(layout)
    assert bindings[top.session_id].scope_status == "bound"
    assert bindings[top.session_id].scope_root_id is None
    assert bindings[legacy.session_id].scope_status == "unassigned"
    assert bindings[missing.session_id].scope_status == "missing"
    assert bindings[missing.session_id].scope_root_id == "nod_missing"
    assert bindings[broken_root.session_id].scope_status == "broken"
    assert bindings[broken_child.session_id].tree_id == broken_root.session_id
    assert bindings[cycle_a.session_id].scope_status == "broken"
    assert bindings[cycle_a.session_id].tree_id == bindings[cycle_b.session_id].tree_id
    assert (
        bindings[cycle_descendant.session_id].tree_id
        == bindings[cycle_a.session_id].tree_id
    )

    list_route = _endpoint(create_app(layout), "/session", "GET")
    assert {
        record["session_id"] for record in list_route("top")["sessions"]
    } == {top.session_id}
    assert {
        record["session_id"]
        for record in list_route("unassigned")["sessions"]
    } == {
        legacy.session_id,
        missing.session_id,
        broken_root.session_id,
        broken_child.session_id,
        cycle_a.session_id,
        cycle_b.session_id,
        cycle_descendant.session_id,
    }


def test_create_session_route_rejects_unknown_scope_before_provider_start(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    create_route = _endpoint(create_app(layout), "/session", "POST")

    with pytest.raises(HTTPException) as missing_scope:
        create_route(
            {
                "text": "hello",
                "provider_id": "codex",
                "scope_root_id": "nod_missing",
            }
        )

    assert missing_scope.value.status_code == 422
    assert "does not exist" in str(missing_scope.value.detail)
    assert list_sessions(layout) == []


def _rewrite_created_details(
    layout: ProjectLayout,
    session_id: str,
    **updates: Any,
) -> None:
    path = layout.dot_dir / "agent" / "sessions" / f"{session_id}.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    created = json.loads(lines[0])
    created["details"].update(updates)
    lines[0] = json.dumps(created, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
