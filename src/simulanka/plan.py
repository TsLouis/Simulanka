"""§14.7 plan-file format v1: parse + deterministic ingest.

A plan file is free-prose Markdown carrying EXACTLY ONE ```simulanka-plan
fenced JSON block. The block's two sections are parsing regimes, not workflow:
``distill`` speaks about entities already on the graph (ids are resolved and
type-checked), ``plan`` mints new ones (lids become @ref handles). Both are
optional; an entirely empty block is rejected.

Ingest translates the block into ONE PatchIntent so the narrative lands
atomically — half a plan on the graph is an inconsistent state. Any failure
rejects the file as a whole and the analyst edits + re-sends (deliberately
unlike the op-block protocol's per-op application: that is interactive chat,
this is a document).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from simulanka.contract import AcceptanceSpec, BudgetSpec, TaskContract, task_node_attrs
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    IntentOp,
    PatchIntent,
    Receipt,
    UpdateAttrsOp,
)
from simulanka.kernel.resolver import resolve_node
from simulanka.kernel.validator import ValidationError
from simulanka.layout.file_registry import managed_dir_node
from simulanka.layout.project import ProjectLayout
from simulanka.registry.file_kinds import FILE_KINDS
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import iter_nodes


class PlanError(ValueError):
    """Plan file rejected; the analyst edits the file and re-sends."""


# ---------------------------------------------------------------------------
# Block schema (§14.7). extra="forbid" everywhere: a typo in an analyst file
# must be a loud rejection, never a silently dropped field.
# ---------------------------------------------------------------------------

ClaimStatus = Literal["open", "supported", "refuted"]
Verdict = Literal["unconfirmed", "correct", "wrong", "uncertain", "disputed"]  # §13.2


class NewClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lid: str
    body: str = Field(min_length=1)
    status: ClaimStatus = "open"


class DistillEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["supports", "contradicts"]
    source: str  # evidence selector (must already be on the graph)
    target: str  # claim/hypothesis selector, or the lid of a new_claims entry
    note: str | None = None


class ClaimUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    status: ClaimStatus
    note: str | None = None


class HypothesisUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    verdict: Verdict
    note: str | None = None


class DistillSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_claims: list[NewClaim] = Field(default_factory=list)
    edges: list[DistillEdge] = Field(default_factory=list)
    claims: list[ClaimUpdate] = Field(default_factory=list)
    hypotheses: list[HypothesisUpdate] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.new_claims or self.edges or self.claims or self.hypotheses)


class PlanQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lid: str
    body: str = Field(min_length=1)


class PlanHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lid: str
    body: str = Field(min_length=1)
    addresses: str  # question lid or graph selector


class PlanTask(BaseModel):
    """Fields are the §5.6 TaskContract vocabulary, flattened."""

    model_config = ConfigDict(extra="forbid")
    lid: str | None = None  # optional; derived t1/t2/… in document order
    goal: str = Field(min_length=1)
    allowed_outputs: list[str] = Field(default_factory=list)
    acceptance: str | None = None
    budget_time_seconds: float | None = None


class PlanExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lid: str
    goal: str = Field(min_length=1)
    tests: str  # hypothesis lid or graph selector
    tasks: list[PlanTask] = Field(default_factory=list)


class PlanSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[PlanQuestion] = Field(default_factory=list)
    hypotheses: list[PlanHypothesis] = Field(default_factory=list)
    experiments: list[PlanExperiment] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.questions or self.hypotheses or self.experiments)


class Escalate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)


class PlanBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    distill: DistillSection = Field(default_factory=DistillSection)
    plan: PlanSection = Field(default_factory=PlanSection)
    escalate: Escalate | None = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```simulanka-plan[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_LID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
# The hyphen keeps this ref outside the lid charset — no analyst lid can collide.
_PLAN_DIR_REF = "plan-dir"


def extract_plan_block(text: str) -> PlanBlock:
    blocks = _FENCE_RE.findall(text)
    if len(blocks) != 1:
        raise PlanError(
            f"expected exactly one ```simulanka-plan fenced block, found {len(blocks)}."
        )
    try:
        data = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise PlanError(f"plan block is not valid JSON: {exc}") from exc
    try:
        block = PlanBlock.model_validate(data)
    except PydanticValidationError as exc:
        raise PlanError(f"plan block failed schema validation:\n{exc}") from exc
    if block.distill.is_empty() and block.plan.is_empty() and block.escalate is None:
        raise PlanError("plan block is empty: nothing to distill, plan, or escalate.")
    return block


@dataclass(frozen=True)
class _Lids:
    new_claims: set[str]
    questions: set[str]
    hypotheses: set[str]
    all: set[str]
    tasks: list[list[str]]  # parallel to plan.experiments[i].tasks[j]


def _assign_lids(block: PlanBlock) -> _Lids:
    """Charset + block-wide uniqueness for every lid; derive missing task lids.

    Explicit task lids are claimed before any derivation so t1/t2/… never
    collides regardless of where an explicit `t3` sits in the document.
    """
    used: set[str] = set()

    def take(lid: str, where: str) -> None:
        if not _LID_RE.match(lid):
            raise PlanError(
                f"{where}: lid `{lid}` is invalid (letter, then letters/digits/underscore)."
            )
        # The escalate note is a sibling of the lid-named atoms; the kernel does
        # not enforce sibling name uniqueness on create (§4 rejects ambiguity at
        # read time instead), so the format reserves the name here.
        if lid == "escalate":
            raise PlanError(f"{where}: `escalate` is a reserved lid.")
        if lid in used:
            raise PlanError(f"{where}: lid `{lid}` is declared more than once in the block.")
        used.add(lid)

    for i, nc in enumerate(block.distill.new_claims):
        take(nc.lid, f"distill.new_claims[{i}]")
    new_claims = {nc.lid for nc in block.distill.new_claims}
    for i, q in enumerate(block.plan.questions):
        take(q.lid, f"plan.questions[{i}]")
    questions = {q.lid for q in block.plan.questions}
    for i, h in enumerate(block.plan.hypotheses):
        take(h.lid, f"plan.hypotheses[{i}]")
    hypotheses = {h.lid for h in block.plan.hypotheses}
    for i, exp in enumerate(block.plan.experiments):
        take(exp.lid, f"plan.experiments[{i}]")
        for j, task in enumerate(exp.tasks):
            if task.lid is not None:
                take(task.lid, f"plan.experiments[{i}].tasks[{j}]")

    counter = 1
    tasks: list[list[str]] = []
    for exp in block.plan.experiments:
        row: list[str] = []
        for task in exp.tasks:
            if task.lid is not None:
                row.append(task.lid)
            else:
                while f"t{counter}" in used:
                    counter += 1
                derived = f"t{counter}"
                used.add(derived)
                row.append(derived)
        tasks.append(row)

    return _Lids(
        new_claims=new_claims, questions=questions, hypotheses=hypotheses,
        all=used, tasks=tasks,
    )


def _lid_or_selector(value: str, member_of: set[str], lids: _Lids, where: str, want: str) -> str:
    """Translate an intra-block lid reference to @ref, or pass a graph selector through."""
    if value in member_of:
        return "@" + value
    if value in lids.all:
        raise PlanError(f"{where}: `{value}` is a lid in this block but not a {want} lid.")
    return value


def _resolved_typed(
    layout: ProjectLayout, selector: str, want: tuple[str, ...], where: str,
) -> Node:
    """Pre-resolve a graph reference for analyst-grade error messages.

    The kernel re-validates inside apply_patch; this exists so a bad reference
    reads as `distill.claims[2]: …` instead of `op[17] update_attrs: …`.
    """
    try:
        node = resolve_node(layout, selector)
    except ValueError as exc:
        raise PlanError(f"{where}: {exc}") from exc
    if node.type not in want:
        raise PlanError(
            f"{where}: `{selector}` is type `{node.type}`, want {' or '.join(want)}."
        )
    return node


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IngestResult:
    file_node_id: str
    plan_dir_id: str
    relative_path: str
    receipt: Receipt
    escalate_reason: str | None


def ingest_plan(layout: ProjectLayout, path: Path) -> IngestResult:
    """Land one plan file on the graph as a single atomic patch.

    The file is archived under ``research/`` (FileRegistry `plan` kind) unless
    it already lives there at a policy-conformant name.
    """
    spec = FILE_KINDS["plan"]
    src = path if path.is_absolute() else Path.cwd() / path
    src = src.resolve()
    try:
        content = src.read_bytes()
    except OSError as exc:
        raise PlanError(f"cannot read `{path}`: {exc}") from exc
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanError(f"`{path}` is not valid UTF-8: {exc}") from exc

    block = extract_plan_block(text)
    lids = _assign_lids(block)

    # -- destination path: in place if already under research/, else archive-copy
    root = layout.root.resolve()
    try:
        rel_src = str(src.relative_to(root)).replace("\\", "/")
    except ValueError:
        rel_src = None
    prefix = (spec.name_prefix or "")
    if rel_src is not None and rel_src.startswith(spec.dir_name + "/"):
        if not Path(rel_src).name.startswith(prefix):
            raise PlanError(
                f"`{rel_src}` is under {spec.dir_name}/ but not named `{prefix}*`; "
                f"rename it to match the plan kind's policy."
            )
        rel = rel_src
        archive_copy = False
    else:
        fname = src.name
        if not fname.startswith(prefix):
            fname = prefix + fname
        if spec.default_extension and "." not in fname:
            fname += spec.default_extension
        rel = f"{spec.dir_name}/{fname}"
        archive_copy = True

    for n in iter_nodes(layout):
        if n.type == "file" and n.attrs.get("fs_path") == rel:
            raise PlanError(
                f"`{rel}` is already ingested (file node {n.id}); "
                f"a plan file lands exactly once (revision flow is v2)."
            )
    dest = layout.root / rel
    if archive_copy and dest.exists():
        raise PlanError(
            f"archive target `{rel}` already exists on disk but is not registered; "
            f"remove it, or ingest that file in place."
        )

    # -- pre-resolve every reference to an already-committed entity
    for i, edge in enumerate(block.distill.edges):
        where = f"distill.edges[{i}]"
        _resolved_typed(layout, edge.source, ("evidence",), f"{where}.source")
        if edge.target not in lids.all:
            _resolved_typed(layout, edge.target, ("claim", "hypothesis"), f"{where}.target")
    claim_updates = [
        _resolved_typed(layout, cu.id, ("claim",), f"distill.claims[{i}]")
        for i, cu in enumerate(block.distill.claims)
    ]
    hypothesis_updates = [
        _resolved_typed(layout, hu.id, ("hypothesis",), f"distill.hypotheses[{i}]")
        for i, hu in enumerate(block.distill.hypotheses)
    ]
    for i, hyp in enumerate(block.plan.hypotheses):
        if hyp.addresses not in lids.all:
            _resolved_typed(
                layout, hyp.addresses, ("question",), f"plan.hypotheses[{i}].addresses",
            )
    for i, exp in enumerate(block.plan.experiments):
        if exp.tests not in lids.all:
            _resolved_typed(
                layout, exp.tests, ("hypothesis",), f"plan.experiments[{i}].tests",
            )

    research_dir = managed_dir_node(layout, "plan")
    base_version = layout.load_manifest().graph_version

    stamp: dict[str, Any] = {"source": "analyst", "plan_file": rel}
    ops: list[IntentOp] = []

    # File node is inlined instead of going through register_file: a failed
    # ingest must leave zero trace — a pre-registered file node would block
    # the fix-and-resend loop (duplicate check above keys on fs_path).
    ops.append(CreateNodeOp(
        type="file", name=Path(rel).name, parent=research_dir.id,
        attrs={
            "fs_path": rel,
            "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
            "kind": spec.name,
            "binding": spec.binding,
            "size_bytes": len(content),
        },
    ))
    # One graph-only directory per plan: lids are block-unique, so per-plan
    # containment is what isolates same-named atoms across rounds.
    ops.append(CreateNodeOp(
        type="directory", name=Path(rel).stem, parent=research_dir.id,
        ref=_PLAN_DIR_REF, attrs=dict(stamp),
    ))

    parent = "@" + _PLAN_DIR_REF
    for nc in block.distill.new_claims:
        ops.append(CreateNodeOp(
            type="claim", name=nc.lid, parent=parent, ref=nc.lid,
            attrs={"body": nc.body, "status": nc.status, **stamp, "plan_lid": nc.lid},
        ))
    for q in block.plan.questions:
        ops.append(CreateNodeOp(
            type="question", name=q.lid, parent=parent, ref=q.lid,
            attrs={"body": q.body, **stamp, "plan_lid": q.lid},
        ))
    for hyp in block.plan.hypotheses:
        ops.append(CreateNodeOp(
            type="hypothesis", name=hyp.lid, parent=parent, ref=hyp.lid,
            attrs={"body": hyp.body, **stamp, "plan_lid": hyp.lid},
        ))
        ops.append(CreateEdgeOp(
            type="addresses", source="@" + hyp.lid,
            target=_lid_or_selector(
                hyp.addresses, lids.questions, lids, "plan.hypotheses.addresses", "question",
            ),
            attrs=dict(stamp),
        ))
    for ei, exp in enumerate(block.plan.experiments):
        ops.append(CreateNodeOp(
            type="experiment", name=exp.lid, parent=parent, ref=exp.lid,
            attrs={"goal": exp.goal, "status": "planned", **stamp, "plan_lid": exp.lid},
        ))
        ops.append(CreateEdgeOp(
            type="tests", source="@" + exp.lid,
            target=_lid_or_selector(
                exp.tests, lids.hypotheses, lids, "plan.experiments.tests", "hypothesis",
            ),
            attrs=dict(stamp),
        ))
        for ti, task in enumerate(exp.tasks):
            contract = TaskContract(
                goal=task.goal,
                allowed_outputs=list(task.allowed_outputs),
                budget=BudgetSpec(time_seconds=task.budget_time_seconds),
                acceptance=(
                    AcceptanceSpec(command=task.acceptance)
                    if task.acceptance is not None else None
                ),
            )
            tlid = lids.tasks[ei][ti]
            ops.append(CreateNodeOp(
                type="task", name=tlid, parent="@" + exp.lid,
                attrs={**task_node_attrs(contract), **stamp, "plan_lid": tlid},
            ))
    for edge in block.distill.edges:
        edge_attrs: dict[str, Any] = dict(stamp)
        if edge.note is not None:
            edge_attrs["note"] = edge.note
        ops.append(CreateEdgeOp(
            type=edge.type, source=edge.source,
            target=_lid_or_selector(
                edge.target, lids.new_claims, lids, "distill.edges.target", "new_claims",
            ),
            attrs=edge_attrs,
        ))
    # Distill rewrites are the analyst's judgment snapshot; the reviewed_in
    # stamp is what §14.9 reads as the `reviewed` trust-level criterion.
    for cu, node in zip(block.distill.claims, claim_updates, strict=True):
        attrs: dict[str, Any] = {"status": cu.status, "reviewed_in": rel}
        if cu.note is not None:
            attrs["note"] = cu.note
        ops.append(UpdateAttrsOp(target=node.id, attrs=attrs))
    for hu, node in zip(block.distill.hypotheses, hypothesis_updates, strict=True):
        attrs = {"verdict": hu.verdict, "reviewed_in": rel}
        if hu.note is not None:
            attrs["note"] = hu.note
        ops.append(UpdateAttrsOp(target=node.id, attrs=attrs))
    if block.escalate is not None:
        ops.append(CreateNodeOp(
            type="note", name="escalate", parent=parent,
            attrs={"kind": "escalate", "body": block.escalate.reason, **stamp},
        ))

    intent = PatchIntent(
        ops=ops, actor="analyst", base_graph_version=base_version,
        note=f"plan ingest {rel}",
    )
    try:
        receipt = apply_patch(layout, intent)
    except ValidationError as exc:
        raise PlanError(f"plan rejected by kernel: {exc}") from exc

    # Archive copy is written only after the patch landed, so a rejected plan
    # leaves no disk trace either (fix-and-resend stays clean).
    if archive_copy:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    return IngestResult(
        file_node_id=receipt.nodes[0],   # ops[0] is the file node,
        plan_dir_id=receipt.nodes[1],    # ops[1] the per-plan directory
        relative_path=rel,
        receipt=receipt,
        escalate_reason=block.escalate.reason if block.escalate is not None else None,
    )
