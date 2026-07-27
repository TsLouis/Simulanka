from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from simulanka.agent.harness import HarnessError
from simulanka.agent.session import (
    OpenCodeAdapter,
    ProviderCapabilities,
    SessionEvent,
    normalize_opencode_event,
    provider_adapters,
    stream_opencode_events,
)
from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateNodeOp
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.server.app import create_app
from simulanka.server.sessions import (
    append_session_event,
    create_work_session,
    load_work_session,
    read_session_events,
    render_first_message,
    stream_work_session_turn,
)


def test_normalize_opencode_text_tool_and_unknown_events() -> None:
    assert normalize_opencode_event(
        {"type": "text", "part": {"type": "text", "text": "hello"}}
    ) == [SessionEvent(type="agent_text", text="hello")]

    tool_events = normalize_opencode_event(
        {
            "type": "tool",
            "part": {
                "type": "tool",
                "tool": "bash",
                "callID": "call_1",
                "state": {
                    "status": "completed",
                    "input": {"command": "pwd"},
                    "output": "/repo",
                },
            },
        }
    )
    assert [event.type for event in tool_events] == ["tool_call", "tool_result"]
    assert tool_events[0].input == {"command": "pwd"}
    assert tool_events[1].output == "/repo"

    [unknown] = normalize_opencode_event({"type": "future-shape", "private": "raw"})
    assert unknown.type == "status"
    assert unknown.details == {"event_type": "future-shape"}
    assert "private" not in unknown.as_dict()


def test_stream_opencode_events_builds_continuation_and_forces_agent_actor() -> None:
    seen: dict[str, Any] = {}

    def runner(args: list[str], env: Mapping[str, str]) -> Iterable[str]:
        seen["args"] = args
        seen["actor"] = env.get("SIMULANKA_ACTOR")
        return [
            json.dumps(
                {
                    "type": "text",
                    "sessionID": "provider-new",
                    "part": {"type": "text", "text": "streamed"},
                }
            )
        ]

    events = list(
        stream_opencode_events(
            "do work",
            session_id="provider-old",
            model="provider/model",
            runner=runner,
        )
    )

    assert seen["actor"] == "agent"
    assert seen["args"] == [
        "opencode",
        "run",
        "--print-logs",
        "--format",
        "json",
        "-m",
        "provider/model",
        "-s",
        "provider-old",
        "do work",
    ]
    assert events == [
        SessionEvent(
            type="agent_text",
            text="streamed",
            provider_session_id="provider-new",
        )
    ]


def test_opencode_adapter_contract_registry_and_native_resume() -> None:
    seen: dict[str, Any] = {}

    def runner(args: list[str], env: Mapping[str, str]) -> Iterable[str]:
        seen["args"] = args
        seen["actor"] = env["SIMULANKA_ACTOR"]
        return []

    adapter = provider_adapters.create("opencode", runner=runner)
    assert isinstance(adapter, OpenCodeAdapter)
    assert adapter.capabilities == ProviderCapabilities(
        native_resume=True,
        native_fork=False,
        interrupt=False,
        tool_events=True,
        usage=False,
    )

    turn = adapter.resume_turn("provider-1", "continue")
    with pytest.raises(HarnessError, match="does not support turn interruption"):
        turn.handle.cancel()
    assert list(turn.events) == []
    assert seen["actor"] == "agent"
    assert seen["args"] == [
        "opencode",
        "run",
        "--print-logs",
        "--format",
        "json",
        "-s",
        "provider-1",
        "continue",
    ]


def test_work_session_uses_one_jsonl_and_preserves_provider_id(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    anchor = {"id": "nod_task", "name": "toy", "goal": "test"}
    state = create_work_session(layout, anchor=anchor, model=None)

    first_prompt = render_first_message(state, "start")
    assert "nod_task" in first_prompt
    append_session_event(
        layout,
        state.session_id,
        SessionEvent(
            type="agent_text",
            text="ready",
            provider_session_id="provider-1",
        ),
    )

    loaded = load_work_session(layout, state.session_id)
    assert loaded.provider_session_id == "provider-1"
    assert loaded.anchor == anchor
    assert render_first_message(loaded, "continue") == "continue"
    session_files = list((layout.dot_dir / "agent" / "sessions").iterdir())
    assert session_files == [
        layout.dot_dir / "agent" / "sessions" / f"{state.session_id}.jsonl"
    ]


def test_server_work_session_streams_ndjson_and_rejects_concurrent_turn(
    tmp_path: Path,
) -> None:
    layout, task_id = _seed_task(tmp_path)
    calls: list[list[str]] = []

    def runner(args: list[str], env: Mapping[str, str]) -> Iterable[str]:
        calls.append(args)
        assert env["SIMULANKA_ACTOR"] == "agent"
        return [
            json.dumps(
                {
                    "type": "step_start",
                    "sessionID": "provider-1",
                    "part": {"type": "step-start"},
                }
            ),
            json.dumps(
                {
                    "type": "text",
                    "sessionID": "provider-1",
                    "part": {"type": "text", "text": "working"},
                }
            ),
        ]

    app = create_app(layout, opencode_stream_runner=runner)
    create_session = _endpoint(app, "/session", "POST")
    send_message = _endpoint(app, "/session/{session_id}/message", "POST")
    history = _endpoint(app, "/session/{session_id}/history", "GET")

    created = create_session({"task": task_id})
    assert created["anchor"]["id"] == task_id
    assert created["anchor"]["goal"] == "visible task"

    first = send_message(created["session_id"], {"text": "begin"})
    assert isinstance(first, StreamingResponse)
    with pytest.raises(HTTPException) as conflict:
        send_message(created["session_id"], {"text": "too soon"})
    assert conflict.value.status_code == 409

    state = load_work_session(layout, created["session_id"])
    events = [
        json.loads(line)
        for line in stream_work_session_turn(
            layout,
            state,
            "begin",
            runner=runner,
        )
    ]
    assert [event["type"] for event in events] == [
        "user_msg",
        "status",
        "status",
        "agent_text",
        "status",
    ]
    assert events[1]["status"] == "running"
    assert events[-1]["status"] == "done"
    assert task_id in calls[0][-1]

    state = load_work_session(layout, created["session_id"])
    list(stream_work_session_turn(layout, state, "continue", runner=runner))
    assert calls[1][-3:-1] == ["-s", "provider-1"]
    stored = history(created["session_id"])
    assert stored["events"] == read_session_events(layout, created["session_id"])


def test_work_session_failure_and_disconnect_never_record_done(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout

    def broken_runner(
        args: list[str], env: Mapping[str, str]
    ) -> Iterable[str]:
        del args, env
        raise RuntimeError("provider unavailable")

    failed = create_work_session(layout, anchor=None, model=None)
    failed_events = [
        json.loads(line)
        for line in stream_work_session_turn(
            layout,
            failed,
            "begin",
            runner=broken_runner,
        )
    ]
    assert [event["type"] for event in failed_events[-2:]] == ["error", "status"]
    assert failed_events[-1]["status"] == "failed"
    assert all(event.get("status") != "done" for event in failed_events)

    provider_error = create_work_session(layout, anchor=None, model=None)
    error_lines = [
        json.dumps(
            {
                "type": "error",
                "message": "model rejected the turn",
            }
        )
    ]
    provider_events = [
        json.loads(line)
        for line in stream_work_session_turn(
            layout,
            provider_error,
            "begin",
            runner=lambda args, env: iter(error_lines),
        )
    ]
    assert provider_events[-2]["type"] == "error"
    assert provider_events[-1]["status"] == "failed"
    assert all(event.get("status") != "done" for event in provider_events)

    interrupted = create_work_session(layout, anchor=None, model=None)
    stream = stream_work_session_turn(
        layout,
        interrupted,
        "begin",
        runner=lambda args, env: iter(["not-json"]),
    )
    assert json.loads(next(stream))["type"] == "user_msg"
    stream.close()
    stored = read_session_events(layout, interrupted.session_id)
    assert stored[-1]["status"] == "failed"
    assert "连接中断" in stored[-1]["text"]


def _seed_task(tmp_path: Path) -> tuple[ProjectLayout, str]:
    layout = init_project(tmp_path, with_scaffold=False).layout
    parent = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="directory", name="tasks", parent=None, attrs={})],
        actor="test",
    ).nodes[0]
    task_id = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(
                type="task",
                name="toy",
                parent=parent,
                attrs={
                    "goal": "visible task",
                    "allowed_outputs": ["result.txt"],
                    "acceptance_command": "test -f result.txt",
                },
            )
        ],
        actor="test",
    ).nodes[0]
    return layout, task_id


def _endpoint(app: FastAPI, path: str, method: str) -> Callable[..., Any]:
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            endpoint = getattr(route, "endpoint", None)
            if callable(endpoint):
                return cast(Callable[..., Any], endpoint)
    raise AssertionError(f"no {method} {path} route")
