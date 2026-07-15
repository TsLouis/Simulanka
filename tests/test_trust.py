"""S6 trust: deterministic level mapping + provenance backtrack.

Trust is computed at query time from existing stamps and never persisted;
the provenance chain shows node and edge levels separately and never folds
them into one score.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp
from simulanka.layout import init_project
from simulanka.layout.project import ProjectLayout
from simulanka.plan import ingest_plan
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import iter_nodes
from simulanka.trust import node_trust, provenance_chain, trust_level

# ---------------------------------------------------------------------------
# trust_level: priority-ordered mapping over existing stamps
# ---------------------------------------------------------------------------


def test_trust_level_priority_order() -> None:
    # human beats everything: a human verdict on a traced edge stays human.
    assert trust_level({"verdict_by": "user", "source": "trace"}) == "human"
    assert trust_level({"source": "trace"}) == "constructed"
    assert trust_level({"source": "machine", "reviewed_in": "research/p.md"}) == "constructed"
    assert trust_level({"reviewed_in": "research/p.md", "checked_by": "tool"}) == "reviewed"
    assert trust_level({"checked_by": "shape-check"}) == "checked"
    assert trust_level({}) == "unreviewed"
    # agent/analyst stamps are not machine observation — honest grey.
    assert trust_level({"source": "agent"}) == "unreviewed"
    assert trust_level({"source": "analyst"}) == "unreviewed"
    # a non-user verdict is not the human level.
    assert trust_level({"verdict_by": "agent"}) == "unreviewed"


def test_node_trust_excludes_questions_and_structure() -> None:
    def node(type_: str, attrs: dict[str, object]) -> Node:
        return Node(
            id="nod_x", type=type_, name="x", parent_id=None, attrs=attrs,
            created_at=datetime.now(tz=UTC), created_by="test",
        )

    # 提问不是断言 (v1): questions carry no trust badge.
    assert node_trust(node("question", {"source": "analyst"})) is None
    assert node_trust(node("module", {})) is None
    assert node_trust(node("evidence", {"source": "machine"})) == "constructed"
    assert node_trust(node("claim", {"reviewed_in": "research/p.md"})) == "reviewed"


# ---------------------------------------------------------------------------
# provenance_chain: claim ← evidence ← run → task → experiment → plan file
# ---------------------------------------------------------------------------

PLAN = """# 分析

```simulanka-plan
{"plan": {"questions": [{"lid": "q1", "body": "why?"}],
          "hypotheses": [{"lid": "h1", "body": "because", "addresses": "q1"}],
          "experiments": [{"lid": "e1", "goal": "try it", "tests": "h1",
                           "tasks": [{"goal": "do it"}]}]},
 "escalate": {"reason": "need a human eye"}}
```
"""


def _by_name(layout: ProjectLayout, name: str) -> Node:
    return next(n for n in iter_nodes(layout) if n.name == name)


def _seed_full_chain(tmp_path: Path) -> ProjectLayout:
    """Real ingest for the plan half, hand-built run/evidence/claim on top."""
    layout = init_project(tmp_path).layout
    plan = tmp_path / "plan-r1.md"
    plan.write_text(PLAN, encoding="utf-8")
    ingest_plan(layout, plan)

    exp = _by_name(layout, "e1")
    task = _by_name(layout, "t1")
    receipt = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(type="run", name="r1", parent=exp.id,
                         attrs={"status": "done"}, ref="run"),
            CreateEdgeOp(type="fulfills", source="@run", target=task.id,
                         attrs={"source": "machine"}),
        ],
        actor="system",
        note="test: run",
    )
    run_id = receipt.nodes[0]
    receipt = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(type="evidence", name="ev1", parent=run_id,
                         attrs={"source": "machine", "metrics": {"acc": 0.9}},
                         ref="ev"),
            CreateEdgeOp(type="produces", source=run_id, target="@ev",
                         attrs={"source": "machine"}),
        ],
        actor="system",
        note="test: evidence",
    )
    ev_id = receipt.nodes[0]
    plan_dir = _by_name(layout, "plan-r1")
    apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(type="claim", name="c1", parent=plan_dir.id,
                         attrs={"status": "open"}, ref="c"),
            CreateEdgeOp(type="supports", source=ev_id, target="@c",
                         attrs={"source": "analyst"}),
        ],
        actor="analyst",
        note="test: claim",
    )
    return layout


def test_provenance_chain_walks_to_plan_file(tmp_path: Path) -> None:
    layout = _seed_full_chain(tmp_path)
    claim = _by_name(layout, "c1")

    chain = provenance_chain(layout, claim.id)

    assert [(h["type"], h["via_edge"]) for h in chain] == [
        ("claim", None),
        ("evidence", "supports"),
        ("run", "produces"),
        ("task", "fulfills"),
        ("experiment", "parent"),
        ("file", "plan_file"),
    ]
    by_type = {h["type"]: h for h in chain}
    # Node and edge are levelled separately: the evidence node is machine
    # measurement, the supports edge is the analyst's (unvetted) judgment.
    assert by_type["evidence"]["trust"] == "constructed"
    assert by_type["evidence"]["via_edge_trust"] == "unreviewed"
    assert by_type["run"]["via_edge_trust"] == "constructed"
    assert by_type["task"]["via_edge_trust"] == "constructed"
    # Structural hops (containment, plan_file attr) assert nothing — no level.
    assert by_type["experiment"]["via_edge_trust"] is None
    assert by_type["file"]["via_edge_trust"] is None
    assert by_type["file"]["name"] == "plan-r1.md"
    # Determinism: same graph, same chain.
    assert provenance_chain(layout, claim.id) == chain


def test_provenance_chain_mid_start_and_unknown(tmp_path: Path) -> None:
    layout = _seed_full_chain(tmp_path)
    run = _by_name(layout, "r1")

    chain = provenance_chain(layout, run.id)
    assert [h["type"] for h in chain] == ["run", "task", "experiment", "file"]

    try:
        provenance_chain(layout, "nod_missing")
    except KeyError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected KeyError for unknown node")


def test_evidence_parent_fallback_without_produces_edge(tmp_path: Path) -> None:
    """An evidence node with a run parent but no produces edge still reaches
    the run — the parent hop is the fallback route."""
    layout = init_project(tmp_path).layout
    baselines = _by_name(layout, "baselines")
    receipt = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(type="experiment", name="exp", parent=baselines.id,
                         attrs={}, ref="exp"),
            CreateNodeOp(type="run", name="r2", parent="@exp", attrs={}, ref="run"),
            CreateNodeOp(type="evidence", name="ev2", parent="@run",
                         attrs={"source": "machine"}),
        ],
        actor="system",
        note="test: bare evidence",
    )
    chain = provenance_chain(layout, receipt.nodes[2])
    assert [(h["type"], h["via_edge"]) for h in chain] == [
        ("evidence", None),
        ("run", "parent"),
    ]
    assert chain[1]["via_edge_trust"] is None
