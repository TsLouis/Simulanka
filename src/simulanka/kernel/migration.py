from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from simulanka.kernel.events import Event, append_event
from simulanka.kernel.ids import new_id
from simulanka.kernel.manifest import (
    REGISTRY_VERSION,
    SCHEMA_VERSION,
    compute_content_hash,
    load_manifest,
    write_manifest,
)
from simulanka.layout.project import ProjectLayout

MigrationKind = Literal["schema", "registry"]


@dataclass(frozen=True)
class Migration:
    name: str
    kind: MigrationKind
    from_version: int
    to_version: int
    apply: Callable[[ProjectLayout], None]


# Real migrations are appended here as schema/registry evolve.
# Empty in Alpha: there is no released prior version to migrate from.
MIGRATIONS: list[Migration] = []


class MigrationError(RuntimeError):
    """Migration plan/execution failed."""


class SchemaMismatch(RuntimeError):
    """Project versions are behind code; writes are blocked until `migrate` runs."""


class PlannedStep(BaseModel):
    name: str
    kind: MigrationKind
    from_version: int
    to_version: int


class MigrationPlan(BaseModel):
    current_schema: int
    target_schema: int
    current_registry: int
    target_registry: int
    steps: list[PlannedStep]

    @property
    def is_empty(self) -> bool:
        return not self.steps


def check_versions(layout: ProjectLayout) -> None:
    """Raise SchemaMismatch if manifest versions are behind code constants."""
    m = layout.load_manifest()
    if m.schema_version != SCHEMA_VERSION or m.registry_version != REGISTRY_VERSION:
        raise SchemaMismatch(
            f"Project versions schema={m.schema_version}, registry={m.registry_version} "
            f"do not match code (schema={SCHEMA_VERSION}, registry={REGISTRY_VERSION}). "
            "Run `simulanka graph migrate` before further writes."
        )


def plan_migrations(layout: ProjectLayout) -> MigrationPlan:
    m = load_manifest(layout)
    steps: list[PlannedStep] = []
    _collect(steps, "schema", m.schema_version, SCHEMA_VERSION)
    _collect(steps, "registry", m.registry_version, REGISTRY_VERSION)
    return MigrationPlan(
        current_schema=m.schema_version,
        target_schema=SCHEMA_VERSION,
        current_registry=m.registry_version,
        target_registry=REGISTRY_VERSION,
        steps=steps,
    )


def run_migrations(layout: ProjectLayout) -> MigrationPlan:
    plan = plan_migrations(layout)
    if plan.is_empty:
        return plan

    manifest = load_manifest(layout)
    ops_log: list[dict[str, object]] = []

    for step in plan.steps:
        mig = _find(step.kind, step.from_version)
        assert mig is not None, "plan_migrations should have caught this"
        mig.apply(layout)
        ops_log.append({
            "kind": "migrate",
            "name": mig.name,
            "migration_kind": mig.kind,
            "from": mig.from_version,
            "to": mig.to_version,
        })

    new_graph_version = manifest.graph_version + 1
    now = datetime.now(UTC)
    event = Event(
        id=new_id("evt"),
        at=now,
        actor="system:migrate",
        kind="migrate",
        base_graph_version=manifest.graph_version,
        graph_version=new_graph_version,
        note=None,
        ops=ops_log,
    )
    append_event(layout, event)

    write_manifest(
        layout,
        manifest.model_copy(update={
            "schema_version": plan.target_schema,
            "registry_version": plan.target_registry,
            "graph_version": new_graph_version,
            "content_hash": compute_content_hash(layout),
        }),
    )
    return plan


def _collect(steps: list[PlannedStep], kind: MigrationKind, current: int, target: int) -> None:
    if current > target:
        raise MigrationError(
            f"{kind} version {current} is ahead of code's {target}. "
            "Downgrade is not supported."
        )
    version = current
    while version < target:
        mig = _find(kind, version)
        if mig is None:
            raise MigrationError(
                f"No {kind} migration registered from v{version}. "
                f"Stuck at v{version}, target v{target}."
            )
        steps.append(PlannedStep(
            name=mig.name,
            kind=kind,
            from_version=mig.from_version,
            to_version=mig.to_version,
        ))
        version = mig.to_version


def _find(kind: MigrationKind, from_version: int) -> Migration | None:
    for m in MIGRATIONS:
        if m.kind == kind and m.from_version == from_version:
            return m
    return None
