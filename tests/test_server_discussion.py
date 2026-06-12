"""§13.6 discussion endpoints: session flow + the agent write-matrix gate.

opencode is faked via the injectable CommandRunner — every test runs without
the real CLI. The fake returns one opencode JSON event whose assistant text
embeds a ``simulanka-ops`` block, exercising the full harness→filter→kernel
path.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    CreatePortOp,
    IntentOp,
    PatchIntent,
)
from simulanka.kernel.manifest import load_manifest
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.server.app import create_app
from simulanka.storage.entity_store import (
    edge_exists,
    find_port,
    iter_edges,
    iter_nodes,
    load_edge,
)


def _apply(layout: ProjectLayout, ops: list[IntentOp]) -> None:
    apply_patch(
        layout,
        PatchIntent(
            ops=ops,
            actor="test",
            base_graph_version=load_manifest(layout).graph_version,
        ),
    )


def _seed(tmp_path: Path) -> tuple[ProjectLayout, dict[str, str]]:
    """Project with two modules; one user edge, one agent ghost, two free
    ports (out1/in1) left unconnected for propose_edge tests."""
    layout = init_project(tmp_path).layout
    baselines = next(n for n in iter_nodes(layout) if n.name == "baselines")
    _apply(layout, [CreateNodeOp(type="model", name="Net", parent=baselines.id, attrs={})])
    net_id = next(n.id for n in iter_nodes(layout) if n.name == "Net")
    _apply(
        layout,
        [
            CreateNodeOp(type="module", name="enc", parent=net_id, attrs={}),
            CreateNodeOp(type="module", name="dec", parent=net_id, attrs={}),
        ],
    )
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "enc")
    dec_id = next(n.id for n in iter_nodes(layout) if n.name == "dec")
    _apply(
        layout,
        [
            CreatePortOp(node=enc_id, name="out0", direction="out", port_type="tensor"),
            CreatePortOp(node=enc_id, name="out1", direction="out", port_type="tensor"),
            CreatePortOp(node=dec_id, name="in0", direction="in", port_type="tensor"),
            CreatePortOp(node=dec_id, name="in1", direction="in", port_type="tensor"),
        ],
    )
    ports = {
        name: port.id
        for node_id, name in ((enc_id, "out0"), (enc_id, "out1"), (dec_id, "in0"), (dec_id, "in1"))
        if (port := find_port(layout, node_id, name)) is not None
    }
    assert len(ports) == 4

    _apply(
        layout,
        [
            CreateEdgeOp(
                type="data_flow",
                source=ports["out0"],
                target=ports["in0"],
                attrs={"source": "user"},
            ),
            CreateEdgeOp(
                type="data_flow",
                source=ports["out1"],
                target=ports["in0"],
                attrs={
                    "source": "agent",
                    "status": "proposed",
                    "verdict": "unconfirmed",
                    "citation": "enc.py:12",
                },
            ),
        ],
    )
    edges = {e.attrs["source"]: e.id for e in iter_edges(layout) if e.type == "data_flow"}
    return layout, {**ports, "user_edge": edges["user"], "ghost": edges["agent"]}


def _fake_runner(
    replies: list[str],
) -> tuple[Callable[[list[str], float], str], list[list[str]]]:
    """CommandRunner double: records argv, plays back canned assistant texts."""
    calls: list[list[str]] = []

    def run(args: list[str], timeout: float) -> str:
        calls.append(args)
        text = replies[min(len(calls) - 1, len(replies) - 1)]
        return json.dumps({"sessionID": "ses_test", "role": "assistant", "text": text})

    return run, calls


def _ops_reply(*ops: dict[str, object]) -> str:
    return "Let me check.\n```simulanka-ops\n" + json.dumps({"ops": list(ops)}) + "\n```\n"


def test_start_without_disagreements_is_422(tmp_path: Path) -> None:
    layout, _ = _seed(tmp_path)
    runner, calls = _fake_runner(["hi"])
    client = TestClient(create_app(layout, opencode_runner=runner))

    resp = client.post("/discussion/start", json={})
    assert resp.status_code == 422
    assert calls == []  # never reached opencode
    assert client.get("/discussion").json() == {"active": False}


def test_start_sends_context_and_enforces_matrix(tmp_path: Path) -> None:
    layout, ids = _seed(tmp_path)
    runner, calls = _fake_runner(
        [
            _ops_reply(
                # verify-pass cell: agent verdict on an undecided user edge — allowed
                {
                    "op": "set_verdict",
                    "edge_id": ids["user_edge"],
                    "attrs": {"verdict": "wrong", "verdict_note": "dec reads cfg, not enc"},
                },
                # the human already ruled this ghost — agent may not overwrite
                {
                    "op": "set_verdict",
                    "edge_id": ids["ghost"],
                    "attrs": {"verdict": "correct", "verdict_note": "but I cited it"},
                },
            )
        ]
    )
    client = TestClient(create_app(layout, opencode_runner=runner))

    # Build the disagreement set: reject the ghost (bucket ①), pull the user
    # edge in by hand (bucket ④).
    r = client.post(
        f"/edge/{ids['ghost']}/verdict",
        json={"verdict": "wrong", "note": "out1 is never consumed"},
    )
    assert r.status_code == 200
    assert client.post(f"/edge/{ids['user_edge']}/discuss", json={}).status_code == 200

    resp = client.post("/discussion/start", json={"model": "prov/m"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["session_id"] == "ses_test"
    assert sorted(payload["batch"]) == sorted([ids["ghost"], ids["user_edge"]])

    # Opening message carries the context: edge ids + the human's note.
    opening = calls[0][-1]
    assert ids["ghost"] in opening and "out1 is never consumed" in opening
    assert "-m" in calls[0] and "prov/m" in calls[0]

    # Matrix: one applied (user edge, verdict_by forced to agent), one rejected.
    assert len(payload["applied"]) == 1
    assert len(payload["rejected"]) == 1
    assert "human verdict stands" in payload["rejected"][0]["reason"]
    user_edge = load_edge(layout, ids["user_edge"])
    assert user_edge.attrs["verdict"] == "wrong"
    assert user_edge.attrs["verdict_by"] == "agent"
    ghost = load_edge(layout, ids["ghost"])
    assert ghost.attrs["verdict_by"] == "user"  # untouched

    state = client.get("/discussion").json()
    assert state["active"] is True and state["session_id"] == "ses_test"


def test_message_continues_session_and_applies_ops(tmp_path: Path) -> None:
    layout, ids = _seed(tmp_path)
    runner, calls = _fake_runner(
        [
            "no ops in the opening",
            _ops_reply(
                {
                    "op": "propose_edge",
                    "source": ids["out1"],
                    "target": ids["in1"],
                    "attrs": {"citation": "dec.py:40", "evidence_locality": "local"},
                },
                {"op": "propose_edge", "source": ids["out1"], "target": ids["in0"], "attrs": {}},
                {"op": "withdraw_edge", "edge_id": ids["ghost"]},
                {"op": "withdraw_edge", "edge_id": ids["user_edge"]},
                {"op": "accept_edge", "edge_id": ids["ghost"]},
            ),
        ]
    )
    client = TestClient(create_app(layout, opencode_runner=runner))
    client.post(
        f"/edge/{ids['ghost']}/verdict",
        json={"verdict": "wrong", "note": "out1 unused"},
    )
    assert client.post("/discussion/start", json={}).status_code == 200

    resp = client.post("/discussion/message", json={"text": "convince me"})
    assert resp.status_code == 200
    payload = resp.json()

    # Session continuation reached opencode with the recorded id.
    assert "-s" in calls[1] and "ses_test" in calls[1]

    # propose with citation → applied, server-forced ghost attrs.
    # propose without citation / withdraw user edge / unknown op → rejected.
    assert len(payload["applied"]) == 2
    assert len(payload["rejected"]) == 3
    reasons = " | ".join(r["reason"] for r in payload["rejected"])
    assert "no citation" in reasons
    assert "un-accepted ghosts" in reasons
    assert "unknown op" in reasons

    new_edge_id = payload["applied"][0]["edge_id"]
    new_edge = load_edge(layout, new_edge_id)
    assert new_edge.attrs["source"] == "agent"
    assert new_edge.attrs["status"] == "proposed"
    assert new_edge.attrs["verdict"] == "unconfirmed"
    assert new_edge.attrs["evidence_locality"] == "local"
    assert not edge_exists(layout, ids["ghost"])  # withdrawn
    assert edge_exists(layout, ids["user_edge"])  # protected


def test_message_without_active_session_is_422(tmp_path: Path) -> None:
    layout, _ = _seed(tmp_path)
    runner, _calls = _fake_runner(["hi"])
    client = TestClient(create_app(layout, opencode_runner=runner))

    resp = client.post("/discussion/message", json={"text": "anyone there?"})
    assert resp.status_code == 422
