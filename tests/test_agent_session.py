from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from simulanka.agent.context import SUPPLEMENT_BOUNDARY_START
from simulanka.agent.harness import HarnessError
from simulanka.agent.session import (
    CodexAdapter,
    OpenCodeAdapter,
    ProcessTurnHandle,
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
    create_session,
    create_work_session,
    load_session,
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


def test_process_turn_handle_honors_prebind_cancel_once() -> None:
    handle = ProcessTurnHandle()
    callbacks: list[str] = []

    handle.cancel()
    handle.cancel()
    handle.bind(lambda: callbacks.append("cancelled"))
    handle.cancel()

    assert handle.cancel_requested is True
    assert callbacks == ["cancelled"]


def test_codex_adapter_uses_native_resume_and_preserves_usage() -> None:
    calls: list[list[str]] = []

    def runner(args: list[str], env: Mapping[str, str]) -> Iterable[str]:
        calls.append(args)
        assert env["SIMULANKA_ACTOR"] == "agent"
        if args[2] == "--json":
            return [
                json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
                json.dumps({"type": "turn.started"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "hello"},
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "call-1",
                            "type": "command_execution",
                            "command": "pwd",
                            "aggregated_output": "/repo",
                            "status": "completed",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 12,
                            "cached_input_tokens": 8,
                            "output_tokens": 3,
                        },
                    }
                ),
            ]
        return [json.dumps({"type": "turn.completed"})]

    adapter = provider_adapters.create("codex", runner=runner)
    assert isinstance(adapter, CodexAdapter)
    assert adapter.capabilities.usage is True
    first_events = list(adapter.start_turn("first message").events)
    assert calls[0] == ["codex", "exec", "--json", "first message"]
    assert first_events[0].provider_session_id == "thread-1"
    assert [event.type for event in first_events] == [
        "status",
        "status",
        "agent_text",
        "tool_call",
        "tool_result",
        "status",
    ]
    assert first_events[-1].details == {
        "usage": {
            "input_tokens": 12,
            "cached_input_tokens": 8,
            "output_tokens": 3,
        }
    }

    message = "second message\n\n<new-supplement>only this turn</new-supplement>"
    resumed_events = list(adapter.resume_turn("thread-1", message).events)
    assert calls[1] == ["codex", "exec", "resume", "thread-1", "--json", message]
    assert resumed_events[-1].details == {}


def test_stop_api_interrupts_one_codex_turn_and_resumes_native_session(
    tmp_path: Path,
) -> None:
    layout, task_id = _seed_task(tmp_path)
    state = create_session(layout, provider_id="codex")
    append_session_event(
        layout,
        state.session_id,
        SessionEvent(
            type="status",
            status="done",
            provider_session_id="thread-keep",
        ),
    )
    calls: list[list[str]] = []

    class BlockingLines:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.released = threading.Event()

        def __iter__(self) -> Iterator[str]:
            self.started.set()
            if not self.released.wait(timeout=5):
                raise AssertionError("stop did not cancel the provider stream")
            yield from ()

        def cancel(self) -> None:
            self.released.set()

    blocking = BlockingLines()

    def runner(args: list[str], env: Mapping[str, str]) -> Iterable[str]:
        del env
        calls.append(args)
        if len(calls) == 1:
            return blocking
        return (json.dumps({"type": "turn.completed"}),)

    app = create_app(layout, opencode_stream_runner=runner)
    send_message = _endpoint(app, "/session/{session_id}/message", "POST")
    stop = _endpoint(app, "/session/{session_id}/stop", "POST")
    providers = _endpoint(app, "/session/providers", "GET")

    capabilities = {
        item["provider_id"]: item["capabilities"]
        for item in providers()["providers"]
    }
    assert capabilities["codex"]["interrupt"] is True
    assert capabilities["opencode"]["interrupt"] is False

    refs = [{"kind": "node", "ref_id": task_id}]
    response = send_message(
        state.session_id,
        {"text": "long turn", "refs": refs},
    )
    iterator = _streaming_iterator(response)
    chunks: list[str] = []
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            chunks.extend(iterator)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=consume)
    worker.start()
    assert blocking.started.wait(timeout=2)
    assert stop(state.session_id, {}) == {"status": "stopping"}
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert errors == []

    interrupted_events = [
        json.loads(line)
        for chunk in chunks
        for line in chunk.splitlines()
        if line.strip()
    ]
    terminal = [
        event.get("status")
        for event in interrupted_events
        if event.get("status") in {"done", "failed", "interrupted"}
    ]
    assert terminal == ["interrupted"]
    interrupted = load_session(layout, state.session_id)
    assert interrupted.status == "interrupted"
    assert interrupted.native_session_id == "thread-keep"

    resumed = send_message(
        state.session_id,
        {"text": "continue", "refs": refs},
    )
    assert _streaming_events(resumed)[-1]["status"] == "done"
    assert [call[:5] for call in calls] == [
        [
            "codex",
            "exec",
            "resume",
            "thread-keep",
            "--json",
        ],
        [
            "codex",
            "exec",
            "resume",
            "thread-keep",
            "--json",
        ],
    ]
    assert calls[0][-1].startswith(
        "long turn\n\n" + SUPPLEMENT_BOUNDARY_START
    )
    assert calls[1][-1].startswith(
        "continue\n\n" + SUPPLEMENT_BOUNDARY_START
    )
    assert "long turn" not in calls[1][-1]


def test_stop_waits_for_native_id_before_exposing_resumable_pause(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout

    def runner(args: list[str], env: Mapping[str, str]) -> Iterable[str]:
        del args, env
        return (
            json.dumps({"type": "thread.started", "thread_id": "thread-ready"}),
            json.dumps({"type": "turn.completed"}),
        )

    app = create_app(layout, opencode_stream_runner=runner)
    create_route = _endpoint(app, "/session", "POST")
    stop = _endpoint(app, "/session/{session_id}/stop", "POST")
    response = create_route({"text": "hello", "provider_id": "codex"})
    session_id = response.headers["x-simulanka-session-id"]

    with pytest.raises(HTTPException) as too_early:
        stop(session_id, {})
    assert too_early.value.status_code == 409
    assert "native session id is not available" in str(too_early.value.detail)
    assert _streaming_events(response)[-1]["status"] == "done"


def test_codex_failed_turn_keeps_nested_error_message() -> None:
    [event] = CodexAdapter.normalize_event(
        {"type": "turn.failed", "error": {"message": "sandbox rejected command"}}
    )

    assert event.type == "error"
    assert event.status == "failed"
    assert event.text == "sandbox rejected command"


def test_provider_workspaces_reach_production_subprocess_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popen_calls: list[tuple[list[str], dict[str, Any]]] = []

    class FakeProcess:
        stdout: list[str] = []

        def __init__(self, args: list[str], **kwargs: Any) -> None:
            popen_calls.append((args, kwargs))

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def poll(self) -> int:
            return 0

        def terminate(self) -> None:
            raise AssertionError("completed fake process must not be terminated")

        def kill(self) -> None:
            raise AssertionError("completed fake process must not be killed")

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    workspace = str(tmp_path / "provider-project")

    assert list(OpenCodeAdapter(workspace=workspace).start_turn("hello").events) == []
    assert list(CodexAdapter(workspace=workspace).start_turn("hello").events) == []
    assert list(OpenCodeAdapter().start_turn("hello").events) == []
    assert list(CodexAdapter().start_turn("hello").events) == []

    assert [kwargs["cwd"] for _, kwargs in popen_calls] == [
        workspace,
        workspace,
        None,
        None,
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


def test_server_lazy_session_streams_context_and_resumes_without_replay(
    tmp_path: Path,
) -> None:
    layout, task_id = _seed_task(tmp_path)
    calls: list[list[str]] = []

    def runner(args: list[str], env: Mapping[str, str]) -> Iterable[str]:
        calls.append(args)
        assert env["SIMULANKA_ACTOR"] == "agent"
        if len(calls) == 1:
            return [
                json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "working"},
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        return [json.dumps({"type": "turn.completed"})]

    app = create_app(layout, opencode_stream_runner=runner)
    start_session = _endpoint(app, "/session", "POST")
    send_message = _endpoint(app, "/session/{session_id}/message", "POST")
    history = _endpoint(app, "/session/{session_id}/history", "GET")
    refs = [{"kind": "node", "ref_id": task_id}]

    first_text = "  begin\n"
    first = start_session(
        {
            "text": first_text,
            "provider_id": "codex",
            "refs": refs,
        }
    )
    assert isinstance(first, StreamingResponse)
    session_id = first.headers["x-simulanka-session-id"]
    with pytest.raises(HTTPException) as conflict:
        send_message(session_id, {"text": "too soon"})
    assert conflict.value.status_code == 409

    events = _streaming_events(first)
    assert [event["type"] for event in events] == [
        "status",
        "user_msg",
        "status",
        "status",
        "agent_text",
        "status",
        "status",
    ]
    assert events[0]["status"] == "created"
    assert events[0]["details"]["session_id"] == session_id
    assert events[0]["details"]["provider_id"] == "codex"
    assert events[1]["text"] == first_text
    assert events[-1]["status"] == "done"
    assert calls[0][:3] == ["codex", "exec", "--json"]
    assert calls[0][-1].startswith(first_text + "\n\n" + SUPPLEMENT_BOUNDARY_START)
    assert task_id in calls[0][-1]

    second_text = "  continue\n"
    second = send_message(session_id, {"text": second_text, "refs": refs})
    second_events = _streaming_events(second)
    assert second_events[0]["text"] == second_text
    assert second_events[0]["details"]["context_bundles"][0]["decision"] == "skip"
    assert second_events[-1]["status"] == "done"
    assert calls[1] == [
        "codex",
        "exec",
        "resume",
        "thread-1",
        "--json",
        second_text,
    ]
    assert first_text not in calls[1][-1]
    assert SUPPLEMENT_BOUNDARY_START not in calls[1][-1]
    assert load_session(layout, session_id).native_session_id == "thread-1"

    stored = history(session_id)
    assert stored["events"] == read_session_events(layout, session_id)

    with pytest.raises(HTTPException) as task_contract:
        start_session({"text": "legacy", "provider_id": "codex", "task": task_id})
    assert task_contract.value.status_code == 422
    assert "task" in task_contract.value.detail

    with pytest.raises(HTTPException) as provider_change:
        send_message(session_id, {"text": "switch", "provider_id": "opencode"})
    assert provider_change.value.status_code == 422


def _streaming_events(response: StreamingResponse) -> list[dict[str, Any]]:
    iterator = _streaming_iterator(response)
    return [
        json.loads(line)
        for chunk in iterator
        for line in chunk.splitlines()
        if line.strip()
    ]


def _streaming_iterator(response: StreamingResponse) -> Iterator[str]:
    frame = getattr(response.body_iterator, "ag_frame", None)
    assert frame is not None
    return cast(Iterator[str], frame.f_locals["iterator"])


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
