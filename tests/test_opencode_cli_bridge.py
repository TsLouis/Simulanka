from __future__ import annotations

import json
from pathlib import Path

from simulanka.agent.harness import DiscussionOp
from simulanka.agent.opencode_cli_bridge import (
    JsonlRecorder,
    build_opencode_argv,
    build_paths,
)
from simulanka.agent.pty_bridge import PtyRead, PtySemanticUpdate


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_build_opencode_argv_uses_interactive_run() -> None:
    assert build_opencode_argv(project=Path("/work")) == [
        "opencode",
        "run",
        "--interactive",
        "--dir",
        "/work",
    ]
    assert build_opencode_argv(
        model="provider/model",
        session_id="ses_1",
        continue_last=True,
        project=Path("/work"),
    ) == [
        "opencode",
        "run",
        "--interactive",
        "-m",
        "provider/model",
        "-s",
        "ses_1",
        "--continue",
        "--dir",
        "/work",
    ]


def test_build_paths_uses_stable_run_name(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, name="run-1")

    assert paths.run_dir == tmp_path / "run-1"
    assert paths.transcript == tmp_path / "run-1" / "transcript.txt"
    assert paths.ops_jsonl == tmp_path / "run-1" / "ops.jsonl"
    assert paths.events_jsonl == tmp_path / "run-1" / "events.jsonl"


def test_jsonl_recorder_writes_transcript_ops_and_errors(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, name="run-1")
    op = DiscussionOp(
        op="update_edge_attrs",
        edge_id="edg_1",
        attrs={"verdict": "correct"},
        raw={
            "op": "update_edge_attrs",
            "edge_id": "edg_1",
            "attrs": {"verdict": "correct"},
        },
    )
    read = PtyRead(
        data=b"raw",
        semantic=PtySemanticUpdate(
            text="clean text\n",
            ops=[op],
            op_errors=["invalid simulanka-ops JSON"],
        ),
        exited=True,
    )

    with JsonlRecorder(paths) as recorder:
        recorder.record_read(read)

    assert paths.transcript.read_text(encoding="utf-8") == "clean text\n"
    assert _jsonl(paths.ops_jsonl)[0]["op"] == op.raw

    events = _jsonl(paths.events_jsonl)
    assert [event["type"] for event in events] == [
        "bridge_start",
        "op",
        "op_error",
        "process_exit",
        "bridge_stop",
    ]
