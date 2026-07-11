from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from simulanka.kernel.manifest import (
    REGISTRY_VERSION,
    SCHEMA_VERSION,
    compute_content_hash,
    load_manifest,
)
from simulanka.layout.project import ProjectLayout
from simulanka.registry.builtin import EDGE_TYPES, NODE_TYPES, PORT_TYPES
from simulanka.registry.file_kinds import FILE_KINDS
from simulanka.storage.entity_store import iter_edges, iter_nodes, iter_ports
from simulanka.storage.index import index_path, rebuild_index, table_counts

Severity = Literal["warn", "error"]


class Issue(BaseModel):
    code: str
    severity: Severity
    message: str
    auto_fixable: bool = False


class DoctorReport(BaseModel):
    ok: bool
    issues: list[Issue]


class RepairResult(BaseModel):
    repaired: list[str]
    skipped: list[str]


def run_doctor(layout: ProjectLayout) -> DoctorReport:
    issues: list[Issue] = []
    issues.extend(_check_versions(layout))
    issues.extend(_check_content_hash(layout))
    issues.extend(_check_parent_cache(layout))
    issues.extend(_check_dangling_refs(layout))
    issues.extend(_check_edge_registry(layout))
    issues.extend(_check_file_nodes(layout))
    issues.extend(_check_untracked_managed_files(layout))
    issues.extend(_check_stale_running_runs(layout))
    issues.extend(_check_index(layout))
    return DoctorReport(ok=not issues, issues=issues)


def repair(layout: ProjectLayout, report: DoctorReport) -> RepairResult:
    """Apply auto-fixes for `auto_fixable` issues. Currently: rebuild the SQLite index."""
    repaired: list[str] = []
    skipped: list[str] = []
    for issue in report.issues:
        if not issue.auto_fixable:
            skipped.append(issue.code)
            continue
        if issue.code == "index_drift":
            rebuild_index(layout)
            repaired.append(issue.code)
        else:
            skipped.append(issue.code)
    return RepairResult(repaired=repaired, skipped=skipped)


def _check_versions(layout: ProjectLayout) -> list[Issue]:
    m = load_manifest(layout)
    out: list[Issue] = []
    if m.schema_version != SCHEMA_VERSION:
        out.append(Issue(
            code="schema_version_mismatch",
            severity="error",
            message=(
                f"manifest.schema_version={m.schema_version} but code uses "
                f"{SCHEMA_VERSION}. Run `simulanka graph migrate`."
            ),
        ))
    if m.registry_version != REGISTRY_VERSION:
        out.append(Issue(
            code="registry_version_mismatch",
            severity="error",
            message=(
                f"manifest.registry_version={m.registry_version} but code uses "
                f"{REGISTRY_VERSION}."
            ),
        ))
    return out


def _check_content_hash(layout: ProjectLayout) -> list[Issue]:
    m = load_manifest(layout)
    actual = compute_content_hash(layout)
    if actual != m.content_hash:
        return [Issue(
            code="content_hash_drift",
            severity="error",
            message=(
                "manifest.content_hash does not match the entity files on disk. "
                "Out-of-band edits or corruption detected. doctor will not auto-fix this."
            ),
        )]
    return []


def _check_parent_cache(layout: ProjectLayout) -> list[Issue]:
    out: list[Issue] = []
    nodes = {n.id: n for n in iter_nodes(layout)}
    contains_parent: dict[str, str] = {}
    for e in iter_edges(layout):
        if e.type == "contains":
            contains_parent[e.target_id] = e.source_id

    for n in nodes.values():
        edge_parent = contains_parent.get(n.id)
        if n.parent_id != edge_parent:
            out.append(Issue(
                code="parent_cache_mismatch",
                severity="warn",
                message=(
                    f"node `{n.id}` parent_id={n.parent_id!r} but contains-edge "
                    f"says parent={edge_parent!r}."
                ),
            ))
    return out


def _check_dangling_refs(layout: ProjectLayout) -> list[Issue]:
    out: list[Issue] = []
    node_ids = {n.id for n in iter_nodes(layout)}
    port_ids = {p.id for p in iter_ports(layout)}

    for p in iter_ports(layout):
        if p.node_id not in node_ids:
            out.append(Issue(
                code="dangling_port",
                severity="error",
                message=f"port `{p.id}` references missing node `{p.node_id}`.",
            ))

    for e in iter_edges(layout):
        node_refs: list[tuple[str, str]] = [
            ("source", e.source_id),
            ("target", e.target_id),
        ]
        for side, ref in node_refs:
            if ref not in node_ids:
                out.append(Issue(
                    code="dangling_edge_node",
                    severity="error",
                    message=f"edge `{e.id}` {side}={ref} not found.",
                ))
        port_refs: list[tuple[str, str | None]] = [
            ("source_port", e.source_port_id),
            ("target_port", e.target_port_id),
        ]
        for side, port_ref in port_refs:
            if port_ref is not None and port_ref not in port_ids:
                out.append(Issue(
                    code="dangling_edge_port",
                    severity="error",
                    message=f"edge `{e.id}` {side}={port_ref} not found.",
                ))
    return out


def _check_edge_registry(layout: ProjectLayout) -> list[Issue]:
    out: list[Issue] = []
    nodes = {n.id: n for n in iter_nodes(layout)}
    ports = {p.id: p for p in iter_ports(layout)}

    for n in nodes.values():
        if n.type not in NODE_TYPES:
            out.append(Issue(
                code="unknown_node_type",
                severity="error",
                message=f"node `{n.id}` has unregistered type `{n.type}`.",
            ))

    for p in ports.values():
        if p.port_type not in PORT_TYPES:
            out.append(Issue(
                code="unknown_port_type",
                severity="warn",
                message=f"port `{p.id}` has unregistered port_type `{p.port_type}`.",
            ))

    for e in iter_edges(layout):
        spec = EDGE_TYPES.get(e.type)
        if spec is None:
            out.append(Issue(
                code="unknown_edge_type",
                severity="error",
                message=f"edge `{e.id}` has unregistered type `{e.type}`.",
            ))
            continue
        src = nodes.get(e.source_id)
        tgt = nodes.get(e.target_id)
        if src and not spec.accepts_source_type(src.type):
            out.append(Issue(
                code="edge_source_type_mismatch",
                severity="error",
                message=(
                    f"edge `{e.id}` type=`{e.type}` rejects source type "
                    f"`{src.type}`."
                ),
            ))
        if tgt and not spec.accepts_target_type(tgt.type):
            out.append(Issue(
                code="edge_target_type_mismatch",
                severity="error",
                message=(
                    f"edge `{e.id}` type=`{e.type}` rejects target type "
                    f"`{tgt.type}`."
                ),
            ))
        if spec.needs_ports:
            sp = ports.get(e.source_port_id) if e.source_port_id else None
            tp = ports.get(e.target_port_id) if e.target_port_id else None
            if sp is None or tp is None:
                out.append(Issue(
                    code="edge_missing_ports",
                    severity="error",
                    message=f"edge `{e.id}` type=`{e.type}` requires ports.",
                ))
                continue
            if spec.source_port_direction and sp.direction != spec.source_port_direction:
                out.append(Issue(
                    code="edge_source_direction",
                    severity="error",
                    message=(
                        f"edge `{e.id}` source port direction `{sp.direction}` "
                        f"!= `{spec.source_port_direction}`."
                    ),
                ))
            if spec.target_port_direction and tp.direction != spec.target_port_direction:
                out.append(Issue(
                    code="edge_target_direction",
                    severity="error",
                    message=(
                        f"edge `{e.id}` target port direction `{tp.direction}` "
                        f"!= `{spec.target_port_direction}`."
                    ),
                ))
    return out


def _check_file_nodes(layout: ProjectLayout) -> list[Issue]:
    out: list[Issue] = []
    for n in iter_nodes(layout):
        if n.type != "file":
            continue
        rel = n.attrs.get("fs_path")
        if not isinstance(rel, str):
            out.append(Issue(
                code="file_node_missing_path",
                severity="error",
                message=f"file node `{n.id}` has no `attrs.fs_path`.",
            ))
            continue
        abs_path = layout.root / rel
        if not abs_path.exists():
            out.append(Issue(
                code="file_missing_on_disk",
                severity="error",
                message=f"file node `{n.id}` references `{rel}` which no longer exists.",
            ))
            continue
        # Reference-binding nodes (e.g. baselines) intentionally don't track
        # content hash — they point at live external trees whose bytes would
        # drift constantly. Existence (checked above) is the only contract.
        binding = n.attrs.get("binding", "managed")
        if binding == "reference":
            continue
        recorded = n.attrs.get("content_hash")
        actual = _hash_path(abs_path)
        if recorded != actual:
            out.append(Issue(
                code="file_hash_drift",
                severity="error",
                message=(
                    f"file `{rel}` content_hash changed since registration "
                    f"(recorded={recorded}, actual={actual})."
                ),
            ))
    return out


def _check_untracked_managed_files(layout: ProjectLayout) -> list[Issue]:
    out: list[Issue] = []
    registered: set[str] = set()
    for n in iter_nodes(layout):
        if n.type == "file":
            rel = n.attrs.get("fs_path")
            if isinstance(rel, str):
                registered.add(rel)
    for spec in FILE_KINDS.values():
        # Only enforce on user-facing managed code/test/doc/paper dirs.
        # Skip reference dirs (baselines, opaque) and artifact dir (transient).
        if spec.binding != "managed" or spec.dir_name.startswith(".simulanka"):
            continue
        root = layout.root / spec.dir_name
        if not root.is_dir():
            continue
        for entry in root.rglob("*"):
            if not entry.is_file():
                continue
            parts = entry.relative_to(layout.root).parts
            if any(p.startswith(".") or p == "__pycache__" for p in parts):
                continue
            rel = str(entry.relative_to(layout.root)).replace("\\", "/")
            if rel not in registered:
                out.append(Issue(
                    code="untracked_managed_file",
                    severity="warn",
                    message=(
                        f"`{rel}` exists under managed dir `{spec.dir_name}/` "
                        f"but is not registered. Run `simulanka graph file register {rel} "
                        f"--kind {spec.name}`."
                    ),
                ))
    return out


_STALE_RUN_FALLBACK_SECONDS = 24 * 3600.0


def _check_stale_running_runs(layout: ProjectLayout) -> list[Issue]:
    """Flag runs stuck in ``running`` past their budget (or 24h without one).

    Orphaned brackets (`run begin` whose harness died) and detached runs whose
    markers were lost both surface here; closing them stays a human act —
    ``run end --status failed`` / ``run status`` — doctor only points.
    """
    out: list[Issue] = []
    now = datetime.now(timezone.utc)
    for n in iter_nodes(layout):
        if n.type != "run" or n.attrs.get("status") != "running":
            continue
        started_raw = n.attrs.get("started_at")
        if not isinstance(started_raw, str):
            continue
        try:
            started = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        age = (now - started).total_seconds()

        budget: float | None = None
        contract = n.attrs.get("contract")
        if isinstance(contract, dict):
            raw_budget = contract.get("budget_time_seconds")
            if isinstance(raw_budget, int | float):
                budget = float(raw_budget)
        threshold = budget if budget is not None else _STALE_RUN_FALLBACK_SECONDS
        if age <= threshold:
            continue

        over = "its time budget" if budget is not None else "24h"
        fix = (
            f"`simulanka run end {n.id} --status failed`"
            if n.attrs.get("bracket") is True
            else f"`simulanka run status {n.id}`"
        )
        out.append(Issue(
            code="stale_running_run",
            severity="warn",
            message=(
                f"run `{n.id}` ({n.name}) has been `running` for {age:.0f}s, "
                f"past {over}. If it is dead, close it with {fix}."
            ),
        ))
    return out


def _hash_path(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _check_index(layout: ProjectLayout) -> list[Issue]:
    if not index_path(layout).exists():
        return []
    counts = table_counts(layout)
    actual = {
        "node": sum(1 for _ in iter_nodes(layout)),
        "edge": sum(1 for _ in iter_edges(layout)),
        "port": sum(1 for _ in iter_ports(layout)),
    }
    if counts != actual:
        return [Issue(
            code="index_drift",
            severity="warn",
            message=(
                f"SQLite index counts {counts} do not match entity files {actual}. "
                "Run `simulanka graph index rebuild` or `doctor --repair`."
            ),
            auto_fixable=True,
        )]
    return []
