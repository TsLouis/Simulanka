from __future__ import annotations

import json

import pytest

from simulanka.agent.harness import (
    DiscussionOp,
    HarnessError,
    assistant_text,
    parse_json_events,
    parse_op_blocks,
    run_opencode_turn,
    session_id_from_events,
)


def test_parse_json_events_accepts_jsonl_array_and_object() -> None:
    assert parse_json_events('{"type":"a"}\n{"type":"b"}') == [
        {"type": "a"},
        {"type": "b"},
    ]
    assert parse_json_events('[{"type":"a"}, "skip"]') == [{"type": "a"}]
    assert parse_json_events('{"type":"single"}') == [{"type": "single"}]
    assert parse_json_events("logs that are not json") == []


def test_assistant_text_handles_common_event_shapes() -> None:
    events: list[dict[str, object]] = [
        {"role": "user", "content": "ignored"},
        {"role": "assistant", "content": "hello"},
        {"message": {"role": "assistant", "content": [{"text": " world"}]}},
        {"role": "assistant", "delta": "!"},
    ]
    assert assistant_text(events) == "hello\n world\n!"


def test_session_id_from_events() -> None:
    assert session_id_from_events([{"sessionID": "ses_1"}]) == "ses_1"
    assert session_id_from_events([{"session": {"id": "ses_2"}}]) == "ses_2"
    assert session_id_from_events([{"message": "none"}]) is None


def test_parse_op_blocks_list_and_errors() -> None:
    text = """I think these should change.

```simulanka-ops
[
  {
    "op": "update_edge_attrs",
    "edge_id": "edg_1",
    "attrs": {"verdict": "wrong", "verdict_by": "agent"}
  },
  {"op": "propose_edge", "source": "enc.out", "target": "dec.in"}
]
```

```simulanka-ops
{"ops": [{"kind": "update_edge_attrs", "edge": "edg_2", "attrs": []}]}
```
"""
    parsed = parse_op_blocks(text)
    assert parsed.ops == [
        DiscussionOp(
            op="update_edge_attrs",
            edge_id="edg_1",
            attrs={"verdict": "wrong", "verdict_by": "agent"},
            raw={
                "op": "update_edge_attrs",
                "edge_id": "edg_1",
                "attrs": {"verdict": "wrong", "verdict_by": "agent"},
            },
        ),
        DiscussionOp(
            op="propose_edge",
            source="enc.out",
            target="dec.in",
            raw={"op": "propose_edge", "source": "enc.out", "target": "dec.in"},
        ),
    ]
    assert parsed.errors == ["op[0]: `attrs` must be an object when present"]


def test_parse_op_blocks_ignores_other_fences() -> None:
    text = """```json
[{"op": "ignored"}]
```
"""
    parsed = parse_op_blocks(text)
    assert parsed.ops == []
    assert parsed.errors == []


def test_run_opencode_turn_builds_command_and_parses() -> None:
    seen: dict[str, object] = {}

    def runner(args: list[str], timeout: float) -> str:
        seen["args"] = args
        seen["timeout"] = timeout
        text = """Looks good.

```simulanka-ops
[{"op": "update_edge_attrs", "edge_id": "edg_1", "attrs": {"verdict": "correct"}}]
```
"""
        return "\n".join(
            [
                json.dumps({"sessionID": "ses_new"}),
                json.dumps({"role": "assistant", "content": text}),
            ]
        )

    turn = run_opencode_turn(
        "continue discussion",
        session_id="ses_old",
        model="provider/model",
        timeout=12.5,
        runner=runner,
    )

    assert seen["args"] == [
        "opencode",
        "run",
        "--print-logs",
        "--format",
        "json",
        "-m",
        "provider/model",
        "-s",
        "ses_old",
        "continue discussion",
    ]
    assert seen["timeout"] == 12.5
    assert turn.session_id == "ses_new"
    assert "Looks good" in turn.text
    assert turn.ops[0].edge_id == "edg_1"
    assert turn.ops[0].attrs["verdict"] == "correct"


def test_run_opencode_turn_rejects_empty_message() -> None:
    with pytest.raises(HarnessError):
        run_opencode_turn("  ", runner=lambda _a, _t: "")
