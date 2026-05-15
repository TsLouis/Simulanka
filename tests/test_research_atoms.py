from __future__ import annotations

from pathlib import Path

import pytest

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp, PatchIntent
from simulanka.kernel.validator import ValidationError
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.storage.entity_store import iter_edges, iter_nodes


def _commit(layout: ProjectLayout, op: CreateNodeOp | CreateEdgeOp) -> None:
    apply_patch(
        layout,
        PatchIntent(
            ops=[op],
            actor="user",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )


def test_create_all_atom_types_under_root_directory(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _commit(layout, CreateNodeOp(type="directory", name="research"))

    # 顶层在 directory 下能创建的：question, experiment
    _commit(layout, CreateNodeOp(
        type="question", name="Q1", parent="/research", attrs={"body": "Does X work?"},
    ))
    _commit(layout, CreateNodeOp(
        type="experiment", name="exp1", parent="/research",
        attrs={"goal": "Test X", "status": "planned"},
    ))

    # hypothesis 在 experiment 下
    _commit(layout, CreateNodeOp(
        type="hypothesis", name="H1", parent="/research/exp1",
        attrs={"body": "X improves accuracy by 1%"},
    ))

    # run 在 experiment 下
    _commit(layout, CreateNodeOp(
        type="run", name="run1", parent="/research/exp1",
        attrs={"status": "running", "command": "python train.py"},
    ))

    # evidence 在 run 下
    _commit(layout, CreateNodeOp(
        type="evidence", name="ev1", parent="/research/exp1/run1",
        attrs={"body": "Test accuracy 87.3% vs baseline 86.1%"},
    ))

    # claim 在 experiment 下
    _commit(layout, CreateNodeOp(
        type="claim", name="C1", parent="/research/exp1",
        attrs={"body": "X improves accuracy", "status": "supported"},
    ))

    # note 附在 run 上
    _commit(layout, CreateNodeOp(
        type="note", name="n1", parent="/research/exp1/run1",
        attrs={"body": "Loss curve looks smooth."},
    ))

    types = {n.type for n in iter_nodes(layout)}
    expected_atoms = {
        "question", "hypothesis", "claim", "evidence",
        "experiment", "run", "note",
    }
    assert expected_atoms.issubset(types)

    # 全程 doctor 应该 ok
    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_semantic_edges_endpoints(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _commit(layout, CreateNodeOp(type="directory", name="research"))
    _commit(layout, CreateNodeOp(type="question", name="Q1", parent="/research"))
    _commit(layout, CreateNodeOp(type="experiment", name="exp1", parent="/research"))
    _commit(layout, CreateNodeOp(type="hypothesis", name="H1", parent="/research/exp1"))
    _commit(layout, CreateNodeOp(type="run", name="run1", parent="/research/exp1"))
    _commit(layout, CreateNodeOp(type="evidence", name="ev1", parent="/research/exp1/run1"))
    _commit(layout, CreateNodeOp(type="claim", name="C1", parent="/research/exp1"))

    # addresses: hypothesis → question
    _commit(layout, CreateEdgeOp(
        type="addresses",
        source="/research/exp1/H1",
        target="/research/Q1",
    ))
    # tests: experiment → hypothesis
    _commit(layout, CreateEdgeOp(
        type="tests",
        source="/research/exp1",
        target="/research/exp1/H1",
    ))
    # part_of: run → experiment
    _commit(layout, CreateEdgeOp(
        type="part_of",
        source="/research/exp1/run1",
        target="/research/exp1",
    ))
    # supports: evidence → claim
    _commit(layout, CreateEdgeOp(
        type="supports",
        source="/research/exp1/run1/ev1",
        target="/research/exp1/C1",
    ))

    edges_by_type = {e.type for e in iter_edges(layout)}
    for t in ("addresses", "tests", "part_of", "supports"):
        assert t in edges_by_type, f"missing edge type {t}"

    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_supports_rejects_non_evidence_source(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _commit(layout, CreateNodeOp(type="directory", name="research"))
    _commit(layout, CreateNodeOp(type="experiment", name="exp1", parent="/research"))
    _commit(layout, CreateNodeOp(type="claim", name="C1", parent="/research/exp1"))
    _commit(layout, CreateNodeOp(type="note", name="n1", parent="/research/exp1"))

    with pytest.raises(ValidationError) as ei:
        _commit(layout, CreateEdgeOp(
            type="supports",
            source="/research/exp1/n1",   # note is not allowed as supports.source
            target="/research/exp1/C1",
        ))
    assert "rejects source" in str(ei.value)


def test_addresses_rejects_reverse_direction(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _commit(layout, CreateNodeOp(type="directory", name="research"))
    _commit(layout, CreateNodeOp(type="question", name="Q1", parent="/research"))
    _commit(layout, CreateNodeOp(type="hypothesis", name="H1", parent="/research"))

    # addresses 必须 hypothesis → question；反向应被拒
    with pytest.raises(ValidationError) as ei:
        _commit(layout, CreateEdgeOp(
            type="addresses",
            source="/research/Q1",
            target="/research/H1",
        ))
    msg = str(ei.value)
    assert "rejects source" in msg or "rejects target" in msg


def test_experiment_cannot_directly_contain_hypothesis_via_wrong_path(tmp_path: Path) -> None:
    """experiment 允许包含 hypothesis；但 model（非容器认可的 atom 父）不行。"""
    layout = init_project(tmp_path, with_scaffold=False).layout
    _commit(layout, CreateNodeOp(type="directory", name="research"))
    _commit(layout, CreateNodeOp(type="model", name="TinyNet", parent="/research"))

    # hypothesis.allow_parents = {directory, experiment}; model 不在列表
    with pytest.raises(ValidationError) as ei:
        _commit(layout, CreateNodeOp(
            type="hypothesis", name="bad", parent="/research/TinyNet",
        ))
    assert "cannot have parent" in str(ei.value)
