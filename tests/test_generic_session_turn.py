from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from simulanka.agent.context import (
    SUPPLEMENT_BOUNDARY_START,
    ContextBundle,
    ContextRef,
    RefSet,
    compile_context,
    decide_context_delivery,
)
from simulanka.agent.session import SessionEvent
from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateNodeOp
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.server.sessions import (
    append_session_event,
    create_session,
    load_session,
    stream_session_turn,
)


def _bundle(tmp_path: Path) -> tuple[ProjectLayout, ContextBundle]:
    layout = init_project(tmp_path, with_scaffold=False).layout
    directory = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="directory", name="context")],
        actor="test",
    ).nodes[0]
    node_id = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(
                type="claim",
                name="context",
                parent=directory,
                attrs={"body": "reference"},
            )
        ],
        actor="test",
    ).nodes[0]
    bundle = compile_context(layout, RefSet((ContextRef("node", node_id),)))
    return layout, bundle


def _events(lines: Iterable[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in lines]


def test_codex_turn_marks_new_context_then_native_resume_skips_it(tmp_path: Path) -> None:
    layout, bundle = _bundle(tmp_path)
    state = create_session(layout, provider_id="codex", workspace=layout.root)
    calls: list[list[str]] = []

    def runner(args: list[str], env: Mapping[str, str]) -> Iterable[str]:
        calls.append(args)
        assert env["SIMULANKA_ACTOR"] == "agent"
        if len(calls) == 1:
            return [
                json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
                json.dumps({"type": "turn.completed"}),
            ]
        return [json.dumps({"type": "turn.completed"})]

    first_message = "  first message\n"
    first = _events(
        stream_session_turn(
            layout,
            state,
            first_message,
            bundles=(bundle,),
            runner=runner,
        )
    )
    assert first[0]["text"] == first_message
    assert first[0]["details"]["context_bundles"] == [
        {
            "digest": bundle.digest,
            "decision": "send",
            "reason": "native_session_pending",
        }
    ]
    assert calls[0][:3] == ["codex", "exec", "--json"]
    assert calls[0][-1].startswith(first_message + "\n\n" + SUPPLEMENT_BOUNDARY_START)
    assert first[-1]["status"] == "done"

    resumed = load_session(layout, state.session_id)
    assert resumed.native_session_id == "thread-1"
    assert decide_context_delivery(layout, "thread-1", bundle).action == "skip"

    second_message = "  second message\n"
    second = _events(
        stream_session_turn(
            layout,
            resumed,
            second_message,
            bundles=(bundle,),
            runner=runner,
        )
    )
    assert calls[1] == [
        "codex",
        "exec",
        "resume",
        "thread-1",
        "--json",
        second_message,
    ]
    assert SUPPLEMENT_BOUNDARY_START not in calls[1][-1]
    assert first_message not in calls[1][-1]
    assert second[0]["details"]["context_bundles"][0]["decision"] == "skip"
    assert second[-1]["status"] == "done"


def test_provider_failure_does_not_mark_context_sent(tmp_path: Path) -> None:
    layout, bundle = _bundle(tmp_path)
    state = create_session(layout, provider_id="codex")

    events = _events(
        stream_session_turn(
            layout,
            state,
            "fail",
            bundles=(bundle,),
            runner=lambda args, env: (
                json.dumps({"type": "thread.started", "thread_id": "thread-failed"}),
                json.dumps({"type": "error", "message": "provider failed"}),
            ),
        )
    )

    assert events[-1]["status"] == "failed"
    assert all(event.get("status") != "done" for event in events)
    assert decide_context_delivery(layout, "thread-failed", bundle).action == "send"


def test_codex_clean_eof_without_completion_never_marks_context_sent(
    tmp_path: Path,
) -> None:
    layout, bundle = _bundle(tmp_path)
    state = create_session(layout, provider_id="codex")
    append_session_event(
        layout,
        state.session_id,
        SessionEvent(
            type="status",
            status="done",
            provider_session_id="thread-incomplete",
        ),
    )

    events = _events(
        stream_session_turn(
            layout,
            load_session(layout, state.session_id),
            "resume",
            bundles=(bundle,),
            runner=lambda args, env: (),
        )
    )

    assert events[-1]["status"] == "failed"
    assert events[-1]["text"] == "Provider 未确认本轮完成"
    assert all(event.get("status") != "done" for event in events)
    assert decide_context_delivery(
        layout,
        "thread-incomplete",
        bundle,
    ).action == "send"


def test_missing_native_id_never_records_done_or_context_sent(tmp_path: Path) -> None:
    layout, bundle = _bundle(tmp_path)
    state = create_session(layout, provider_id="codex")

    events = _events(
        stream_session_turn(
            layout,
            state,
            "missing",
            bundles=(bundle,),
            runner=lambda args, env: (json.dumps({"type": "turn.completed"}),),
        )
    )

    assert events[-1]["status"] == "native_missing"
    assert all(event.get("status") != "done" for event in events)
    assert not (layout.dot_dir / "agent" / "sent-contexts").exists()


def test_opencode_uses_the_same_generic_runtime_and_event_store(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    state = create_session(layout, provider_id="opencode")

    events = _events(
        stream_session_turn(
            layout,
            state,
            "hello",
            runner=lambda args, env: (
                json.dumps(
                    {
                        "type": "text",
                        "sessionID": "open-1",
                        "part": {"type": "text", "text": "world"},
                    }
                ),
            ),
        )
    )

    assert [event["type"] for event in events] == [
        "user_msg",
        "status",
        "agent_text",
        "status",
    ]
    assert events[2]["text"] == "world"
    assert events[-1]["status"] == "done"
    assert load_session(layout, state.session_id).native_session_id == "open-1"


def test_chat_scope_never_becomes_implicit_supplement(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    scope_root_id = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="directory", name="scope")],
        actor="test",
    ).nodes[0]
    state = create_session(
        layout,
        provider_id="codex",
        scope_root_id=scope_root_id,
    )
    calls: list[list[str]] = []

    def runner(args: list[str], env: Mapping[str, str]) -> Iterable[str]:
        del env
        calls.append(args)
        return (
            json.dumps({"type": "thread.started", "thread_id": "thread-scope"}),
            json.dumps({"type": "turn.completed"}),
        )

    message = "  keep this byte-for-byte\n"
    events = _events(
        stream_session_turn(
            layout,
            state,
            message,
            bundles=(),
            runner=runner,
        )
    )

    assert calls == [["codex", "exec", "--json", message]]
    assert events[0]["text"] == message
    assert events[0].get("details", {}) == {}
    assert events[-1]["status"] == "done"
