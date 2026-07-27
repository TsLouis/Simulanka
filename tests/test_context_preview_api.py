from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, HTTPException

from simulanka.agent.context import ContextRef, RefSet, compile_context, mark_context_sent
from simulanka.agent.session import SessionEvent
from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateNodeOp
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.server.app import create_app
from simulanka.server.sessions import append_session_event, create_session


def _endpoint(app: FastAPI, path: str, method: str) -> Callable[..., Any]:
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            endpoint = getattr(route, "endpoint", None)
            if callable(endpoint):
                return cast(Callable[..., Any], endpoint)
    raise AssertionError(f"no {method} {path} route")


def _layout_with_node(tmp_path: Path) -> tuple[ProjectLayout, str]:
    layout = init_project(tmp_path, with_scaffold=False).layout
    directory = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="directory", name="context")],
        actor="test",
    ).nodes[0]
    node_id = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="claim", name="claim", parent=directory, attrs={"body": "source"})],
        actor="test",
    ).nodes[0]
    return layout, node_id


def test_context_preview_new_session_is_send_and_does_not_write_ledger(tmp_path: Path) -> None:
    layout, node_id = _layout_with_node(tmp_path)
    preview = _endpoint(create_app(layout), "/session/context/preview", "POST")

    payload = preview({"refs": [{"kind": "node", "ref_id": node_id}]})

    assert payload["delivery"] == {"action": "send", "reason": "new_session"}
    assert payload["bundle"]["payload"] == payload["payload"]
    assert payload["sources"] == [{"kind": "node", "id": node_id}]
    assert not (layout.dot_dir / "agent" / "sent-contexts").exists()


def test_context_preview_empty_refs_skip_but_still_validate_session(tmp_path: Path) -> None:
    layout, _ = _layout_with_node(tmp_path)
    preview = _endpoint(create_app(layout), "/session/context/preview", "POST")

    empty = preview({"refs": []})
    assert empty["bundle"] is None
    assert empty["payload"] == {"instruction": [], "reference": []}
    assert empty["delivery"] == {"action": "skip", "reason": "no_supplement"}
    with pytest.raises(HTTPException) as unknown:
        preview({"refs": [], "session_id": "ses_01J00000000000000000000000"})
    assert unknown.value.status_code == 404


def test_context_preview_reads_native_ledger_without_marking(tmp_path: Path) -> None:
    layout, node_id = _layout_with_node(tmp_path)
    session = create_session(layout, provider_id="codex")
    append_session_event(
        layout,
        session.session_id,
        SessionEvent(type="status", provider_session_id="native-1"),
    )
    preview = _endpoint(create_app(layout), "/session/context/preview", "POST")
    request = {"refs": [{"kind": "node", "ref_id": node_id}], "session_id": session.session_id}

    first = preview(request)
    assert first["delivery"] == {"action": "send", "reason": "new_digest"}
    assert not (layout.dot_dir / "agent" / "sent-contexts").exists()

    bundle = compile_context(layout, RefSet((ContextRef("node", node_id),)))
    mark_context_sent(layout, "native-1", bundle)
    ledger = next((layout.dot_dir / "agent" / "sent-contexts").iterdir())
    before = ledger.read_bytes()
    repeated = preview(request)
    assert repeated["delivery"] == {"action": "skip", "reason": "already_sent"}
    assert ledger.read_bytes() == before


def test_context_preview_native_pending_session_sends_valid_refs(tmp_path: Path) -> None:
    layout, node_id = _layout_with_node(tmp_path)
    session = create_session(layout, provider_id="codex")
    preview = _endpoint(create_app(layout), "/session/context/preview", "POST")

    response = preview(
        {"refs": [{"kind": "node", "ref_id": node_id}], "session_id": session.session_id}
    )

    assert response["delivery"] == {"action": "send", "reason": "native_session_pending"}


def test_context_preview_omits_or_rejects_missing_refs_and_rejects_native_id(
    tmp_path: Path,
) -> None:
    layout, _ = _layout_with_node(tmp_path)
    preview = _endpoint(create_app(layout), "/session/context/preview", "POST")
    missing_ref = {"kind": "node", "ref_id": "missing"}

    with pytest.raises(HTTPException) as rejected:
        preview({"refs": [missing_ref]})
    assert rejected.value.status_code == 422
    omitted = preview({"refs": [missing_ref], "missing": "omit"})
    assert omitted["omissions"] == [
        {"kind": "node", "ref_id": "missing", "reason": "not_found"}
    ]
    assert omitted["bundle"] is not None
    assert omitted["delivery"] == {"action": "skip", "reason": "no_resolved_content"}

    with pytest.raises(HTTPException) as native_id:
        preview({"refs": [], "native_session_id": "forbidden"})
    assert native_id.value.status_code == 422


def test_context_preview_rejects_unknown_session_and_snapshot_conflict(
    tmp_path: Path,
) -> None:
    layout, node_id = _layout_with_node(tmp_path)
    preview = _endpoint(create_app(layout), "/session/context/preview", "POST")
    with pytest.raises(HTTPException) as unknown:
        preview({"refs": [], "session_id": "ses_01J00000000000000000000000"})
    assert unknown.value.status_code == 404
    with pytest.raises(HTTPException) as conflict:
        preview({"refs": [{"kind": "node", "ref_id": node_id}], "expected_graph_version": 0})
    assert conflict.value.status_code == 409
