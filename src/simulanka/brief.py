"""§14 brief export: the graph → the analyst's opening document.

Mirror-dual of ``plan ingest``: every id the brief prints is directly citable
in the next plan file's ``distill`` section — especially evidence ids, without
which the next round's supports/contradicts edges would have nothing to point
at.

Everything in the block is deterministic and sorted by id: the same graph
state always produces byte-identical output. No timestamps, no prose written
by a model — this is a measurement of the graph, not a summary of it.

Openness criteria (v1, computed at query time):

* claim — ``status == "open"``
* hypothesis — no ``verdict`` stamped
* question — always listed
* "recent" runs — every run under a not-yet-``done`` experiment (flipping an
  experiment to done is the operator's mechanical act)
* escalation — ``status != "resolved"`` (resolution is an explicit human act;
  a later ingest never auto-mutes a stop signal)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from simulanka.disagreements import disagreement_list
from simulanka.layout.file_registry import create_file
from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import iter_nodes

BRIEF_FENCE = "simulanka-brief"


@dataclass(frozen=True)
class BriefResult:
    markdown: str
    relative_path: str | None = None  # set when --out wrote a registered file
    file_node_id: str | None = None


def export_brief(layout: ProjectLayout, *, out: str | None = None) -> BriefResult:
    """Render the brief; with *out*, also write it as a registered ``brief`` file.

    *out* is a brief **name**, not a free path — FileRegistry owns the layout
    and places it at ``research/brief-<name>.md`` (``actor="system"``: the
    exporter is a measuring tool, not an author).
    """
    markdown = render_brief(layout)
    if out is None:
        return BriefResult(markdown=markdown)

    result = create_file(
        layout, "brief", out, markdown.encode("utf-8"), actor="system",
    )
    return BriefResult(
        markdown=markdown,
        relative_path=result.relative_path,
        file_node_id=result.node_id,
    )


def render_brief(layout: ProjectLayout) -> str:
    nodes = sorted(iter_nodes(layout), key=lambda n: n.id)

    questions = [n for n in nodes if n.type == "question"]
    hypotheses = [
        n for n in nodes if n.type == "hypothesis" and not n.attrs.get("verdict")
    ]
    claims = [
        n for n in nodes if n.type == "claim" and n.attrs.get("status") == "open"
    ]
    open_experiments = [
        n for n in nodes
        if n.type == "experiment" and n.attrs.get("status") != "done"
    ]
    open_exp_ids = {n.id for n in open_experiments}
    recent_runs = [n for n in nodes if n.type == "run" and n.parent_id in open_exp_ids]
    escalations = [
        n for n in nodes
        if n.type == "note"
        and n.attrs.get("kind") == "escalate"
        and n.attrs.get("status") != "resolved"
    ]

    block = {
        "open": {
            "questions": [_atom_entry(n) for n in questions],
            "hypotheses": [_atom_entry(n) for n in hypotheses],
            "claims": [{**_atom_entry(n), "status": "open"} for n in claims],
        },
        "recent_runs": [_run_entry(n, nodes) for n in recent_runs],
        "escalations": [
            {
                "id": n.id,
                "body": n.attrs.get("body"),
                "plan_file": n.attrs.get("plan_file"),
            }
            for n in escalations
        ],
        "disagreements": len(disagreement_list(layout)),
        "budget": [_budget_entry(n, nodes) for n in open_experiments],
    }

    lines = [
        f"# Simulanka brief (graph v{layout.load_manifest().graph_version})",
        "",
        f"- Open questions: {len(questions)}",
        f"- Open hypotheses: {len(hypotheses)}",
        f"- Open claims: {len(claims)}",
        f"- Active experiments: {len(open_experiments)}",
        f"- Recent runs: {len(recent_runs)}",
        f"- Unresolved escalations: {len(escalations)}",
        f"- Disagreement set: {block['disagreements']} edge(s)",
    ]
    if escalations:
        lines += ["", "## ESCALATE — unresolved stop signals"]
        for n in escalations:
            origin = n.attrs.get("plan_file")
            suffix = f" (from `{origin}`)" if origin else ""
            lines.append(f"- `{n.id}` {n.attrs.get('body')}{suffix}")
    lines += [
        "",
        f"```{BRIEF_FENCE}",
        json.dumps(block, indent=2, sort_keys=True, ensure_ascii=False),
        "```",
        "",
    ]
    return "\n".join(lines)


def _atom_entry(n: Node) -> dict[str, Any]:
    return {"id": n.id, "name": n.name, "body": n.attrs.get("body")}


def _run_entry(run: Node, nodes: list[Node]) -> dict[str, Any]:
    contract = run.attrs.get("contract")
    task_goal = contract.get("goal") if isinstance(contract, dict) else None
    contract_check = run.attrs.get("contract_check")
    check_status = (
        contract_check.get("status") if isinstance(contract_check, dict) else None
    )
    evidence = [
        {"id": n.id, "metrics": n.attrs.get("metrics")}
        for n in nodes
        if n.type == "evidence" and n.parent_id == run.id
    ]
    return {
        "id": run.id,
        "name": run.name,
        "status": run.attrs.get("status"),
        "task_goal": task_goal,
        "contract_check": check_status,
        "duration_seconds": run.attrs.get("duration_seconds"),
        "evidence": evidence,
    }


def _budget_entry(exp: Node, nodes: list[Node]) -> dict[str, Any]:
    spent = 0.0
    spent_any = False
    budget = 0.0
    budget_any = False
    for n in nodes:
        if n.parent_id != exp.id:
            continue
        if n.type == "run":
            d = n.attrs.get("duration_seconds")
            if isinstance(d, int | float):
                spent += float(d)
                spent_any = True
        elif n.type == "task":
            b = n.attrs.get("budget_time_seconds")
            if isinstance(b, int | float):
                budget += float(b)
                budget_any = True
    return {
        "experiment_id": exp.id,
        "name": exp.name,
        "spent_seconds": spent if spent_any else None,
        "budget_seconds": budget if budget_any else None,
    }
