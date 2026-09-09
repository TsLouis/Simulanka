from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from simulanka.cli.app import app
from simulanka.kernel import migration as migration_mod
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.bundle import export_bundle
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.events import iter_events
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp, CreatePortOp, PatchIntent
from simulanka.kernel.migration import (
    Migration,
    SchemaMismatch,
    plan_migrations,
    run_migrations,
)
from simulanka.layout.project import ProjectLayout, init_project


def _bump_manifest_schema_to(layout: ProjectLayout, version: int) -> None:
    """Rewrite manifest.schema_version to *version* (simulating an old project)."""
    payload = json.loads(layout.manifest_path.read_text("utf-8"))
    payload["schema_version"] = version
    layout.manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _bump_manifest_registry_to(layout: ProjectLayout, version: int) -> None:
    """Rewrite manifest.registry_version to *version* (simulating an old project)."""
    payload = json.loads(layout.manifest_path.read_text("utf-8"))
    payload["registry_version"] = version
    layout.manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_empty_plan_is_noop(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    plan = plan_migrations(layout)
    assert plan.is_empty
    # 仍能跑过 run_migrations，且 manifest 不变
    before = layout.load_manifest().model_dump_json()
    run_migrations(layout)
    after = layout.load_manifest().model_dump_json()
    assert before == after


def test_schema_mismatch_blocks_writes(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _bump_manifest_schema_to(layout, 0)

    with pytest.raises(SchemaMismatch):
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreateNodeOp(type="directory", name="models")],
                actor="user",
                base_graph_version=0,
            ),
        )


def test_read_paths_still_work_when_out_of_date(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="models")],
            actor="user",
            base_graph_version=0,
        ),
    )
    _bump_manifest_schema_to(layout, 0)

    # doctor 和 export 不应被版本不一致挡住（doctor 会报版本警告，export 仅读取）
    report = run_doctor(layout)
    codes = [i.code for i in report.issues]
    assert "schema_version_mismatch" in codes  # doctor 自己识别到了

    bundle = export_bundle(layout)
    assert any(n.name == "models" for n in bundle.nodes)


def test_run_migrations_with_injected_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    # 制造"项目在 v0，代码在 v1"的情形
    _bump_manifest_schema_to(layout, 0)

    applied: list[str] = []

    def fake_apply(_layout: ProjectLayout) -> None:
        applied.append("schema_v0_to_v1")

    fake = Migration(
        name="schema_v0_to_v1",
        kind="schema",
        from_version=0,
        to_version=1,
        apply=fake_apply,
    )
    monkeypatch.setattr(migration_mod, "MIGRATIONS", [fake])

    plan = plan_migrations(layout)
    assert [s.name for s in plan.steps] == ["schema_v0_to_v1"]

    run_migrations(layout)
    assert applied == ["schema_v0_to_v1"]

    m = layout.load_manifest()
    assert m.schema_version == 1
    # graph_version 也前进了一档，并产生 migrate 事件
    events = list(iter_events(layout))
    migrate_events = [e for e in events if e.kind == "migrate"]
    assert len(migrate_events) == 1
    assert migrate_events[0].ops[0]["name"] == "schema_v0_to_v1"


def test_registry_v1_to_v2_only_updates_manifest_and_event(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    for op in (
        CreateNodeOp(type="directory", name="models"),
        CreateNodeOp(type="model", name="TinyNet", parent="/models"),
        CreateNodeOp(type="module", name="source", parent="/models/TinyNet"),
        CreateNodeOp(type="module", name="target", parent="/models/TinyNet"),
        CreatePortOp(
            node="/models/TinyNet/source",
            name="out",
            direction="out",
            port_type="tensor",
        ),
        CreatePortOp(
            node="/models/TinyNet/target",
            name="in",
            direction="in",
            port_type="tensor",
        ),
        CreateEdgeOp(
            type="data_flow",
            source="/models/TinyNet/source.out",
            target="/models/TinyNet/target.in",
        ),
    ):
        apply_patch(
            layout,
            PatchIntent(
                ops=[op],
                actor="test",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )

    _bump_manifest_registry_to(layout, 1)
    before_manifest = layout.load_manifest()
    before_entities = {
        path.relative_to(layout.graph_dir): path.read_bytes()
        for directory in (layout.nodes_dir, layout.edges_dir, layout.ports_dir)
        for path in sorted(directory.glob("*.json"))
    }

    plan = plan_migrations(layout)
    assert [(step.kind, step.from_version, step.to_version) for step in plan.steps] == [
        ("registry", 1, 2)
    ]
    run_migrations(layout)

    after_manifest = layout.load_manifest()
    after_entities = {
        path.relative_to(layout.graph_dir): path.read_bytes()
        for directory in (layout.nodes_dir, layout.edges_dir, layout.ports_dir)
        for path in sorted(directory.glob("*.json"))
    }
    assert after_entities == before_entities
    assert after_manifest.schema_version == before_manifest.schema_version == 1
    assert after_manifest.registry_version == 2
    assert after_manifest.graph_version == before_manifest.graph_version + 1
    assert after_manifest.content_hash == before_manifest.content_hash

    migration_event = list(iter_events(layout))[-1]
    assert migration_event.kind == "migrate"
    assert migration_event.ops == [
        {
            "kind": "migrate",
            "name": "registry_v1_to_v2",
            "migration_kind": "registry",
            "from": 1,
            "to": 2,
        }
    ]


def test_missing_migration_chain_errors_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _bump_manifest_schema_to(layout, 0)
    monkeypatch.setattr(migration_mod, "MIGRATIONS", [])  # 已经是空的，显式确认
    with pytest.raises(migration_mod.MigrationError) as ei:
        plan_migrations(layout)
    assert "No schema migration" in str(ei.value)


def test_cli_migrate_noop(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "proj"
    runner.invoke(app, ["init", str(project)])
    env = {"SIMULANKA_PROJECT": str(project)}
    result = runner.invoke(app, ["graph", "migrate"], env=env)
    assert result.exit_code == 0, result.output
    assert "Nothing to migrate" in result.output


def test_cli_write_blocked_then_migrate_unblocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    project = tmp_path / "proj"
    runner.invoke(app, ["init", str(project)])
    layout = ProjectLayout(project.resolve())
    _bump_manifest_schema_to(layout, 0)
    env = {"SIMULANKA_PROJECT": str(project)}

    # 注入 v0→v1 schema 迁移
    def noop(_l: ProjectLayout) -> None:
        return None

    monkeypatch.setattr(
        migration_mod,
        "MIGRATIONS",
        [Migration(
            name="schema_v0_to_v1",
            kind="schema",
            from_version=0,
            to_version=1,
            apply=noop,
        )],
    )

    blocked = runner.invoke(
        app, ["graph", "node", "create", "--type", "directory", "--name", "x"], env=env
    )
    assert blocked.exit_code == 2
    assert "migrate" in blocked.output

    dry = runner.invoke(app, ["graph", "migrate", "--dry-run"], env=env)
    assert dry.exit_code == 0
    assert "dry-run" in dry.output

    apply_result = runner.invoke(app, ["graph", "migrate"], env=env)
    assert apply_result.exit_code == 0
    assert "Migration applied" in apply_result.output

    after = runner.invoke(
        app, ["graph", "node", "create", "--type", "directory", "--name", "x"], env=env
    )
    assert after.exit_code == 0, after.output
