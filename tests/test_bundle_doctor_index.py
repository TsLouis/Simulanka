from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.bundle import (
    ImportTargetNotEmpty,
    export_bundle,
    import_bundle,
    read_bundle,
    write_bundle,
)
from simulanka.kernel.doctor import repair, run_doctor
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp, CreatePortOp, PatchIntent
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.storage.entity_store import iter_nodes
from simulanka.storage.index import index_path, rebuild_index, table_counts


def _populate(layout: ProjectLayout) -> None:
    """Build a small graph: /models/TinyNet/{conv1,bn1} with one data_flow edge."""
    plans: list[tuple[str, str, str | None]] = [
        ("directory", "models", None),
        ("model", "TinyNet", "/models"),
        ("module", "conv1", "/models/TinyNet"),
        ("module", "bn1", "/models/TinyNet"),
    ]
    for type_, name, parent in plans:
        apply_patch(
            layout,
            PatchIntent(
                ops=[CreateNodeOp(type=type_, name=name, parent=parent)],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    for node, direction, port_name in (
        ("/models/TinyNet/conv1", "out", "out"),
        ("/models/TinyNet/bn1", "in", "in"),
    ):
        apply_patch(
            layout,
            PatchIntent(
                ops=[
                    CreatePortOp(
                        node=node,
                        name=port_name,
                        direction=direction,  # type: ignore[arg-type]
                        port_type="tensor",
                    )
                ],
                actor="user",
                base_graph_version=layout.load_manifest().graph_version,
            ),
        )
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreateEdgeOp(
                    type="data_flow",
                    source="/models/TinyNet/conv1.out",
                    target="/models/TinyNet/bn1.in",
                )
            ],
            actor="user",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )


def test_doctor_clean_on_fresh_graph(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _populate(layout)
    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_doctor_detects_content_hash_drift(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _populate(layout)
    # 篡改一个 node 文件
    sample_node = next(iter_nodes(layout))
    path = layout.nodes_dir / f"{sample_node.id}.json"
    payload = json.loads(path.read_text("utf-8"))
    payload["name"] = "TAMPERED"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = run_doctor(layout)
    codes = [i.code for i in report.issues]
    assert "content_hash_drift" in codes


def test_doctor_repair_fixes_index_drift(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _populate(layout)
    rebuild_index(layout)
    assert run_doctor(layout).ok

    # Corrupt the index by inserting a bogus row.
    import sqlite3
    with sqlite3.connect(index_path(layout)) as conn:
        conn.execute("INSERT INTO node(id, type, name, created_at) VALUES (?,?,?,?)",
                     ("nod_PHANTOM", "directory", "ghost", "2026-05-15T00:00:00Z"))
        conn.commit()

    pre = run_doctor(layout)
    assert any(i.code == "index_drift" and i.auto_fixable for i in pre.issues)

    result = repair(layout, pre)
    assert "index_drift" in result.repaired

    post = run_doctor(layout)
    assert post.ok, [i.model_dump() for i in post.issues]


def test_doctor_warns_on_parent_cache_drift(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _populate(layout)
    # 手动改 parent_id 让它和 contains 边不一致
    sample = next(n for n in iter_nodes(layout) if n.name == "conv1")
    path = layout.nodes_dir / f"{sample.id}.json"
    payload = json.loads(path.read_text("utf-8"))
    payload["parent_id"] = None
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = run_doctor(layout)
    codes = [i.code for i in report.issues]
    assert "parent_cache_mismatch" in codes
    # 也会同时报 content_hash drift（这是篡改的副作用，符合预期）
    assert "content_hash_drift" in codes


def test_export_then_import_roundtrip(tmp_path: Path) -> None:
    src = init_project(tmp_path / "src", with_scaffold=False).layout
    _populate(src)

    bundle = export_bundle(src)
    bundle_path = tmp_path / "snapshot.json"
    write_bundle(bundle, bundle_path)

    restored_bundle = read_bundle(bundle_path)
    target = import_bundle(restored_bundle, tmp_path / "dst")

    # 实体计数、id、manifest 关键字段一致
    src_nodes = {n.id for n in iter_nodes(src)}
    dst_nodes = {n.id for n in iter_nodes(target)}
    assert src_nodes == dst_nodes

    src_m = src.load_manifest()
    dst_m = target.load_manifest()
    assert dst_m.project_id == src_m.project_id
    assert dst_m.graph_version == src_m.graph_version
    assert dst_m.content_hash == src_m.content_hash

    # doctor 在目标上 ok
    report = run_doctor(target)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_import_refuses_existing_target(tmp_path: Path) -> None:
    src = init_project(tmp_path / "src", with_scaffold=False).layout
    _populate(src)
    bundle = export_bundle(src)

    # 目标已是一个 simulanka 项目
    init_project(tmp_path / "dst", with_scaffold=False)
    with pytest.raises(ImportTargetNotEmpty):
        import_bundle(bundle, tmp_path / "dst")


def test_index_counts_match_entities(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _populate(layout)
    rebuild_index(layout)
    counts = table_counts(layout)
    # 4 nodes + 3 contains + 1 data_flow + 2 ports
    assert counts == {"node": 4, "edge": 4, "port": 2}
