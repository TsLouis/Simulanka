"""S4 universal file viewer: GET /file/content — read registered file nodes.

The graph is the authority on what is readable: unregistered paths 404 even
when the bytes exist on disk; binary and over-cap files are reported, not
mangled.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from simulanka.layout import init_project
from simulanka.layout.file_registry import create_file
from simulanka.layout.project import ProjectLayout
from simulanka.plan import ingest_plan
from simulanka.server.app import FILE_CONTENT_CAP, create_app
from simulanka.storage.entity_store import iter_nodes


def _client(tmp_path: Path) -> tuple[TestClient, ProjectLayout]:
    layout = init_project(tmp_path).layout
    return TestClient(create_app(layout)), layout


def test_read_by_node_id(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    created = create_file(
        layout, "doc", "notes", b"# Hello\n\nworld\n",
    )
    resp = client.get("/file/content", params={"node": created.node_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == created.node_id
    assert body["kind"] == "doc"
    assert body["fs_path"] == created.relative_path
    assert body["content"] == "# Hello\n\nworld\n"
    assert body["binary"] is False
    assert body["truncated"] is False


def test_read_by_path_serves_plan_deep_link(tmp_path: Path) -> None:
    """The deep-link case: a research atom's `plan_file` attr is a path — the
    endpoint resolves it to the registered file node and serves the source."""
    client, layout = _client(tmp_path)
    plan = tmp_path / "plan-r1.md"
    plan.write_text(
        '# 分析\n\n```simulanka-plan\n{"plan": {"questions": '
        '[{"lid": "q1", "body": "why?"}]}}\n```\n',
        encoding="utf-8",
    )
    ingest_plan(layout, plan)

    question = next(n for n in iter_nodes(layout) if n.type == "question")
    plan_file = question.attrs["plan_file"]
    assert isinstance(plan_file, str)

    resp = client.get("/file/content", params={"path": plan_file})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fs_path"] == plan_file
    assert question.attrs["plan_lid"] in body["content"]


def test_unregistered_path_404s_even_if_on_disk(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    (tmp_path / "sneaky.txt").write_text("exists but unregistered", encoding="utf-8")
    resp = client.get("/file/content", params={"path": "sneaky.txt"})
    assert resp.status_code == 404


def test_non_file_node_422(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    directory = next(n for n in iter_nodes(layout) if n.type == "directory")
    resp = client.get("/file/content", params={"node": directory.id})
    assert resp.status_code == 422


def test_unknown_node_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    resp = client.get("/file/content", params={"node": "nod_missing"})
    assert resp.status_code == 404


def test_param_exclusivity(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    created = create_file(layout, "doc", "x", b"hi")
    assert client.get("/file/content").status_code == 422
    both = client.get(
        "/file/content",
        params={"node": created.node_id, "path": created.relative_path},
    )
    assert both.status_code == 422


def test_missing_on_disk_404(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    created = create_file(layout, "doc", "gone", b"soon deleted")
    (tmp_path / created.relative_path).unlink()
    resp = client.get("/file/content", params={"node": created.node_id})
    assert resp.status_code == 404


def test_binary_reported_not_mangled(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    created = create_file(layout, "doc", "blob", b"PK\x00\x01binarystuff")
    resp = client.get("/file/content", params={"node": created.node_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["binary"] is True
    assert body["content"] is None


def test_oversize_truncated_flagged(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    big = "x" * (FILE_CONTENT_CAP + 100)
    created = create_file(layout, "doc", "big", big.encode())
    resp = client.get("/file/content", params={"node": created.node_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is True
    assert body["size_bytes"] == FILE_CONTENT_CAP + 100
    assert len(body["content"]) == FILE_CONTENT_CAP


def test_run_log_readable(tmp_path: Path) -> None:
    """Run stdout/stderr are registered file nodes — readable for free (the
    人肉彩排 'everything visible in the frontend' closure piece)."""
    from simulanka.runner import exec_run

    client, layout = _client(tmp_path)
    result = exec_run(
        layout, command="echo hello-from-run", parent="/docs", name="say-hi",
    )
    resp = client.get("/file/content", params={"path": result.stdout_path})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "run_log"
    assert "hello-from-run" in body["content"]


def test_metrics_json_readable_when_registered(tmp_path: Path) -> None:
    client, layout = _client(tmp_path)
    created = create_file(
        layout, "config", "metrics", json.dumps({"acc": 0.9}).encode(),
    )
    resp = client.get("/file/content", params={"node": created.node_id})
    assert resp.status_code == 200
    assert json.loads(resp.json()["content"]) == {"acc": 0.9}
