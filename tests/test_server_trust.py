"""S6/S7 server surface: payload trust, node locator, provenance, note resolve."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.plan import ingest_plan
from simulanka.schema.entities import Node
from simulanka.server.app import create_app
from simulanka.storage.entity_store import iter_nodes

PLAN = """# 分析

```simulanka-plan
{"plan": {"questions": [{"lid": "q1", "body": "why?"}],
          "hypotheses": [{"lid": "h1", "body": "because", "addresses": "q1"}],
          "experiments": [{"lid": "e1", "goal": "try it", "tests": "h1",
                           "tasks": [{"goal": "do it"}]}]},
 "escalate": {"reason": "need a human eye"}}
```
"""


def _seed(tmp_path: Path) -> tuple[TestClient, ProjectLayout]:
    layout = init_project(tmp_path).layout
    plan = tmp_path / "plan-r1.md"
    plan.write_text(PLAN, encoding="utf-8")
    ingest_plan(layout, plan)
    return TestClient(create_app(layout)), layout


def _by_name(layout: ProjectLayout, name: str) -> Node:
    return next(n for n in iter_nodes(layout) if n.name == name)


def test_graph_payload_carries_trust(tmp_path: Path) -> None:
    client, layout = _seed(tmp_path)
    plan_dir = _by_name(layout, "plan-r1")
    resp = client.get("/graph", params={"root": plan_dir.id})
    assert resp.status_code == 200, resp.text
    by_name = {n["name"]: n for n in resp.json()["nodes"]}
    # 提问不是断言: questions carry no badge. Fresh analyst atoms are honest grey.
    assert by_name["q1"]["trust"] is None
    assert by_name["h1"]["trust"] == "unreviewed"
    assert by_name["e1"]["trust"] == "unreviewed"
    assert by_name["escalate"]["trust"] == "unreviewed"


def test_node_locator(tmp_path: Path) -> None:
    client, layout = _seed(tmp_path)
    task = _by_name(layout, "t1")
    exp = _by_name(layout, "e1")
    resp = client.get(f"/node/{task.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "id": task.id, "type": "task", "name": "t1", "parent_id": exp.id,
    }
    assert client.get("/node/nod_missing").status_code == 404


def test_provenance_endpoint(tmp_path: Path) -> None:
    client, layout = _seed(tmp_path)
    task = _by_name(layout, "t1")
    resp = client.get(f"/node/{task.id}/provenance")
    assert resp.status_code == 200, resp.text
    chain = resp.json()["chain"]
    assert [(h["type"], h["via_edge"]) for h in chain] == [
        ("task", None),
        ("experiment", "parent"),
        ("file", "plan_file"),
    ]
    assert client.get("/node/nod_missing/provenance").status_code == 404


def test_resolve_escalate_note(tmp_path: Path) -> None:
    client, layout = _seed(tmp_path)
    note = _by_name(layout, "escalate")
    assert note.attrs["status"] == "open"

    resp = client.post(f"/node/{note.id}/resolve", json={"resolve_note": "已看，继续"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["node_id"] == note.id
    assert body["status"] == "resolved"

    refreshed = _by_name(layout, "escalate")
    assert refreshed.attrs["status"] == "resolved"
    assert refreshed.attrs["resolve_note"] == "已看，继续"

    # Resolving twice is the wrapped 422 — the stop signal clears exactly once.
    resp = client.post(f"/node/{note.id}/resolve", json={})
    assert resp.status_code == 422


def test_resolve_rejects_non_escalate(tmp_path: Path) -> None:
    client, layout = _seed(tmp_path)
    question = _by_name(layout, "q1")
    resp = client.post(f"/node/{question.id}/resolve", json={})
    assert resp.status_code == 422
    assert "not an escalate note" in resp.text
