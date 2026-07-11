"""Metrics file → evidence node: deterministic measurement projection.

A metrics file is a flat JSON dict of scalars (str / int / float / bool).
Extraction only records what was measured — it never judges: the evidence
node gets ``source="machine"`` and **no** supports/contradicts edges; the
semantic reading belongs to the analyst.

Honesty rules (would rather record nothing than something false):

* Any null, nested dict, or list anywhere → the whole file is rejected, no
  partial extraction. The rejection itself is recorded on the run node as
  ``metrics_error``.
* Idempotent: re-extracting identical metrics is a no-op that reports the
  existing evidence node. Changed metrics mint a *new* evidence node — the
  old one is history and history is not rewritten.

``run end --metrics`` and manual ``evidence extract`` share this one path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp, IntentOp, UpdateAttrsOp
from simulanka.kernel.resolver import resolve_node
from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Node
from simulanka.storage.entity_store import iter_nodes

Scalar = str | int | float | bool

_SYSTEM_ACTOR = "system"


class EvidenceError(RuntimeError):
    """Usage-level failure: bad run selector, metrics file not found, ..."""


class MetricsError(EvidenceError):
    """The metrics file exists but its content is invalid.

    By the time this is raised the rejection has already been recorded on the
    run node as ``metrics_error`` — absence of evidence is itself bookkept.
    """


@dataclass(frozen=True)
class EvidenceResult:
    evidence_node_id: str
    created: bool  # False = identical metrics already extracted (no-op)
    metrics: dict[str, Scalar]
    metrics_path: str


def extract_evidence(
    layout: ProjectLayout,
    *,
    run: str,
    metrics: Path | None = None,
) -> EvidenceResult:
    """Extract *run*'s metrics file into an ``evidence`` node.

    ``metrics`` defaults to ``<workdir>/metrics.json`` (workdir from the run
    node). A missing file is a plain :class:`EvidenceError`; an unparseable
    or non-scalar file is a :class:`MetricsError` and stamps ``metrics_error``
    on the run node.
    """
    run_node = _resolve_run(layout, run)
    metrics_path = _resolve_metrics_path(layout, run_node, metrics)

    parsed = _parse_metrics(layout, run_node, metrics_path)
    metrics_rel = _rel_to_root(metrics_path, layout.root)

    siblings = [
        n for n in iter_nodes(layout)
        if n.type == "evidence" and n.parent_id == run_node.id
    ]
    for existing in siblings:
        if existing.attrs.get("metrics") == parsed:
            return EvidenceResult(
                evidence_node_id=existing.id,
                created=False,
                metrics=parsed,
                metrics_path=metrics_rel,
            )

    body = ", ".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    name = f"evidence-{len(siblings) + 1}"
    ops: list[IntentOp] = [
        CreateNodeOp(
            type="evidence",
            name=name,
            parent=run_node.id,
            attrs={
                "source": "machine",
                "metrics": parsed,
                "metrics_path": metrics_rel,
                "body": body,
            },
            ref="ev",
        ),
        CreateEdgeOp(type="produces", source=run_node.id, target="@ev"),
    ]
    if run_node.attrs.get("metrics_error") is not None:
        ops.append(UpdateAttrsOp(target=run_node.id, attrs={"metrics_error": None}))

    receipt = apply_patch_now(
        layout,
        ops=ops,
        actor=_SYSTEM_ACTOR,
        note=f"evidence extract: {run_node.name} -> {name}",
    )
    return EvidenceResult(
        evidence_node_id=receipt.nodes[0],
        created=True,
        metrics=parsed,
        metrics_path=metrics_rel,
    )


def default_metrics_path(layout: ProjectLayout, run_node: Node) -> Path:
    """The conventional location: ``<workdir>/metrics.json``."""
    workdir = Path(str(run_node.attrs.get("workdir", ".")))
    if not workdir.is_absolute():
        workdir = layout.root / workdir
    return workdir / "metrics.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_run(layout: ProjectLayout, selector: str) -> Node:
    try:
        node = resolve_node(layout, selector)
    except ValueError as exc:
        raise EvidenceError(f"run selector {selector!r}: {exc}") from exc
    if node.type != "run":
        raise EvidenceError(
            f"{selector!r}: node is type `{node.type}`, not `run`."
        )
    return node


def _resolve_metrics_path(
    layout: ProjectLayout, run_node: Node, metrics: Path | None,
) -> Path:
    if metrics is not None:
        path = metrics if metrics.is_absolute() else layout.root / metrics
        if not path.is_file():
            raise EvidenceError(f"metrics file {metrics} not found.")
        return path
    path = default_metrics_path(layout, run_node)
    if not path.is_file():
        raise EvidenceError(
            f"no metrics file: {_rel_to_root(path, layout.root)} does not exist "
            "(pass --metrics to point elsewhere)."
        )
    return path


def _parse_metrics(
    layout: ProjectLayout, run_node: Node, metrics_path: Path,
) -> dict[str, Scalar]:
    rel = _rel_to_root(metrics_path, layout.root)

    def reject(reason: str) -> MetricsError:
        message = f"metrics file {rel}: {reason}"
        apply_patch_now(
            layout,
            ops=[UpdateAttrsOp(target=run_node.id, attrs={"metrics_error": message})],
            actor=_SYSTEM_ACTOR,
            note=f"evidence extract rejected: {run_node.name}",
        )
        return MetricsError(message)

    try:
        raw = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise reject(f"not valid JSON ({exc}).") from exc
    if not isinstance(raw, dict):
        raise reject("top level must be a JSON object.")
    if not raw:
        raise reject("empty object — nothing was measured.")

    out: dict[str, Scalar] = {}
    for key, value in raw.items():
        if not isinstance(value, str | int | float | bool):
            raise reject(
                f"key {key!r} is {type(value).__name__} — only flat scalars "
                "(str/int/float/bool) are accepted, no partial extraction."
            )
        out[str(key)] = value
    return out


def _rel_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)
