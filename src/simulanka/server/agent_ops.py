"""§13.6 agent op-block channel: the server-side write-matrix gate.

The discussion agent holds no write tools — its chat replies embed
``simulanka-ops`` blocks, parsed into :class:`DiscussionOp` by the Codex
harness. This module is the only path from those intents to the kernel,
and it enforces the intent-domain matrix cells the agent may write:

- ``set_verdict``   — its own verdict layer; never over a human verdict.
- ``propose_edge``  — new ghosts, citation required (propose.py discipline).
- ``withdraw_edge`` — its own un-accepted ghosts only.

Everything else (accepting/deleting real edges, ``verdict_by``, real-domain
attrs like ``shape_check``) is rejected with a reason that goes back into
the chat. Protocol pinned with Codex in issue #2.

Ops apply one by one: a bad op is reported, not fatal to the batch. The
precondition read and the kernel write are separate steps — same
single-user tolerance as the human-side endpoints (a vanished edge
surfaces as a kernel rejection, not a crash).
"""

from __future__ import annotations

from typing import Any

from simulanka.agent.harness import DiscussionOp
from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateEdgeOp, DeleteEdgeOp, UpdateAttrsOp
from simulanka.kernel.validator import ValidationError
from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Edge
from simulanka.storage.entity_store import load_edge

AGENT_VERDICTS = ("correct", "wrong", "uncertain")
PROPOSE_OPTIONAL_ATTRS = ("output_slice", "evidence_locality")

IntentOp = CreateEdgeOp | DeleteEdgeOp | UpdateAttrsOp


class _Reject(Exception):
    """Why an agent op is refused — the message goes back into the chat."""


def apply_agent_ops(
    layout: ProjectLayout, ops: list[DiscussionOp]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter + apply agent ops; returns ``(applied, rejected)`` summaries."""
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for op in ops:
        try:
            intent = _translate(layout, op)
            receipt = apply_patch_now(
                layout,
                ops=[intent],
                actor="agent",
                note=f"discussion: {op.op}",
            )
        except _Reject as exc:
            rejected.append({"op": op.raw, "reason": str(exc)})
            continue
        except ValidationError as exc:
            rejected.append({"op": op.raw, "reason": f"kernel rejected: {exc}"})
            continue
        applied.append(
            {
                "op": op.raw,
                "edge_id": (receipt.edges + receipt.updated_edges + receipt.deleted_edges)[0],
                "graph_version": receipt.graph_version,
            }
        )
    return applied, rejected


def _translate(layout: ProjectLayout, op: DiscussionOp) -> IntentOp:
    if op.op == "set_verdict":
        return _set_verdict(layout, op)
    if op.op == "propose_edge":
        return _propose_edge(op)
    if op.op == "withdraw_edge":
        return _withdraw_edge(layout, op)
    raise _Reject(
        f"unknown op {op.op!r} — allowed: set_verdict, propose_edge, withdraw_edge"
    )


def _set_verdict(layout: ProjectLayout, op: DiscussionOp) -> UpdateAttrsOp:
    edge = _load_data_flow(layout, op)
    if edge.attrs.get("verdict_by") == "user":
        raise _Reject(
            "human verdict stands — argue in chat; only the human can change it"
        )
    verdict = op.attrs.get("verdict")
    if verdict not in AGENT_VERDICTS:
        raise _Reject(f"verdict must be one of {', '.join(AGENT_VERDICTS)}")
    note = op.attrs.get("verdict_note")
    if not isinstance(note, str) or not note.strip():
        raise _Reject("verdict_note is required — state the evidence")
    return UpdateAttrsOp(
        target=edge.id,
        attrs={
            "verdict": verdict,
            "verdict_by": "agent",
            "verdict_note": note.strip(),
        },
    )


def _propose_edge(op: DiscussionOp) -> CreateEdgeOp:
    if not op.source or not op.target:
        raise _Reject("propose_edge needs source and target port ids")
    citation = op.attrs.get("citation")
    if not isinstance(citation, str) or not citation.strip():
        raise _Reject("no citation — a guess, not a cited edge")
    attrs: dict[str, Any] = {
        "source": "agent",
        "status": "proposed",
        "verdict": "unconfirmed",
        "citation": citation.strip(),
    }
    for key in PROPOSE_OPTIONAL_ATTRS:
        value = op.attrs.get(key)
        if isinstance(value, str) and value.strip():
            attrs[key] = value.strip()
    return CreateEdgeOp(
        type="data_flow", source=op.source, target=op.target, attrs=attrs
    )


def _withdraw_edge(layout: ProjectLayout, op: DiscussionOp) -> DeleteEdgeOp:
    edge = _load_data_flow(layout, op)
    if not (
        edge.attrs.get("source") == "agent"
        and edge.attrs.get("status") == "proposed"
    ):
        raise _Reject("only the agent's own un-accepted ghosts can be withdrawn")
    return DeleteEdgeOp(edge=edge.id)


def _load_data_flow(layout: ProjectLayout, op: DiscussionOp) -> Edge:
    if not op.edge_id:
        raise _Reject(f"{op.op} needs edge_id")
    try:
        edge = load_edge(layout, op.edge_id)
    except FileNotFoundError:
        raise _Reject(f"unknown edge {op.edge_id!r}") from None
    if edge.type != "data_flow":
        raise _Reject("agent ops apply to data_flow edges only")
    return edge
