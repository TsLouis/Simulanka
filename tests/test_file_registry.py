from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from simulanka.cli.app import app
from simulanka.kernel.doctor import run_doctor
from simulanka.layout.file_registry import (
    REFERENCE_HASH_SENTINEL,
    FileRegistryError,
    create_file,
    register_file,
)
from simulanka.layout.project import init_project
from simulanka.storage.entity_store import iter_nodes


def test_create_managed_file_via_api(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout

    result = create_file(layout, "code", "hello", b"print('hi')\n")

    assert result.relative_path == "src/hello.py"
    assert (layout.root / "src" / "hello.py").is_file()
    assert result.kind == "code"
    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_create_test_kind_auto_prefixes_and_extension(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    result = create_file(layout, "test", "smoke", b"")
    assert result.relative_path == "tests/test_smoke.py"


def test_create_refuses_reference_kind(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    with pytest.raises(FileRegistryError) as ei:
        create_file(layout, "baseline", "resnet50", b"")
    assert "reference" in str(ei.value)


def test_create_refuses_overwriting_existing(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    create_file(layout, "code", "dup", b"a")
    with pytest.raises(FileRegistryError):
        create_file(layout, "code", "dup", b"b")


def test_register_existing_file(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    (layout.root / "src" / "manual.py").write_text("# manual\n", encoding="utf-8")

    result = register_file(layout, "code", Path("src/manual.py"))
    assert result.relative_path == "src/manual.py"

    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_register_rejects_path_outside_kind_dir(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    (layout.root / "docs" / "misplaced.py").write_text("# wrong\n", encoding="utf-8")
    with pytest.raises(FileRegistryError) as ei:
        register_file(layout, "code", Path("docs/misplaced.py"))
    assert "not under managed dir" in str(ei.value)


def test_register_baseline_as_directory(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    baseline = layout.root / "baselines" / "resnet50"
    baseline.mkdir(parents=True)
    (baseline / "config.json").write_text("{}\n", encoding="utf-8")
    (baseline / "weights.bin").write_bytes(b"\x00" * 64)

    result = register_file(layout, "baseline", Path("baselines/resnet50"))
    assert result.relative_path == "baselines/resnet50"

    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_register_baseline_via_symlink_to_external_dir(tmp_path: Path) -> None:
    """Reference-kind entries must allow in-project symlinks to external paths.

    Use case: a baseline repo lives outside the project (e.g. on a remote
    sshfs mount). A symlink under baselines/ stands in for it. The containment
    check must not follow the symlink.
    """
    layout = init_project(tmp_path).layout
    external = tmp_path.parent / "external_baseline_repo"
    external.mkdir()
    (external / "README.md").write_text("external\n", encoding="utf-8")

    symlink = layout.root / "baselines" / "ext"
    symlink.symlink_to(external, target_is_directory=True)

    result = register_file(layout, "baseline", Path("baselines/ext"))
    assert result.relative_path == "baselines/ext"

    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_reference_baseline_records_sentinel_hash(tmp_path: Path) -> None:
    """Reference-bound nodes should not snapshot content — record sentinel."""
    layout = init_project(tmp_path).layout
    baseline = layout.root / "baselines" / "external_repo"
    baseline.mkdir(parents=True)
    (baseline / "code.py").write_text("x = 1\n", encoding="utf-8")

    result = register_file(layout, "baseline", Path("baselines/external_repo"))

    node = next(
        n for n in iter_nodes(layout)
        if n.type == "file" and n.attrs.get("fs_path") == result.relative_path
    )
    assert node.attrs["content_hash"] == REFERENCE_HASH_SENTINEL
    assert node.attrs["binding"] == "reference"
    assert node.attrs["size_bytes"] is None


def test_doctor_ignores_drift_in_reference_dir(tmp_path: Path) -> None:
    """Reference dirs are live trees — their bytes changing must not flag drift."""
    layout = init_project(tmp_path).layout
    baseline = layout.root / "baselines" / "live"
    baseline.mkdir(parents=True)
    (baseline / "a.txt").write_text("v1\n", encoding="utf-8")
    register_file(layout, "baseline", Path("baselines/live"))

    # Mutate after registration — simulates upstream change.
    (baseline / "a.txt").write_text("v2 — changed\n", encoding="utf-8")
    (baseline / "new_file.txt").write_text("added later\n", encoding="utf-8")

    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_doctor_still_flags_missing_reference_dir(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    baseline = layout.root / "baselines" / "gone"
    baseline.mkdir(parents=True)
    register_file(layout, "baseline", Path("baselines/gone"))

    shutil.rmtree(baseline)

    report = run_doctor(layout)
    codes = [i.code for i in report.issues]
    assert "file_missing_on_disk" in codes


def test_register_rejects_dotdot_escape(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    with pytest.raises(FileRegistryError) as ei:
        register_file(layout, "baseline", Path("baselines/../../etc/passwd"))
    assert "outside the project root" in str(ei.value)


def test_doctor_detects_missing_file_after_registration(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    create_file(layout, "code", "ephemeral", b"x")
    (layout.root / "src" / "ephemeral.py").unlink()
    report = run_doctor(layout)
    codes = [i.code for i in report.issues]
    assert "file_missing_on_disk" in codes


def test_doctor_detects_file_hash_drift(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    create_file(layout, "doc", "notes", b"original")
    (layout.root / "docs" / "notes.md").write_bytes(b"edited externally")
    report = run_doctor(layout)
    codes = [i.code for i in report.issues]
    assert "file_hash_drift" in codes


def test_doctor_warns_on_untracked_managed_file(tmp_path: Path) -> None:
    layout = init_project(tmp_path).layout
    # Drop a file under src/ without going through FileRegistry.
    (layout.root / "src" / "rogue.py").write_text("# rogue\n", encoding="utf-8")
    report = run_doctor(layout)
    codes = [i.code for i in report.issues]
    assert "untracked_managed_file" in codes
    # The hint should mention the register command.
    rogue_issue = next(i for i in report.issues if i.code == "untracked_managed_file")
    assert "file register" in rogue_issue.message


def test_cli_file_create(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(project)]).exit_code == 0
    env = {"SIMULANKA_PROJECT": str(project)}

    result = runner.invoke(
        app,
        ["graph", "file", "create", "--kind", "doc", "--name", "intro"],
        env=env,
    )
    assert result.exit_code == 0, result.output
    assert "path = docs/intro.md" in result.output
    assert (project / "docs" / "intro.md").is_file()


def test_cli_file_register(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "proj"
    runner.invoke(app, ["init", str(project)])
    env = {"SIMULANKA_PROJECT": str(project)}

    (project / "papers" / "draft.md").write_text("# Draft\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["graph", "file", "register", "papers/draft.md", "--kind", "paper"],
        env=env,
    )
    assert result.exit_code == 0, result.output
    assert "Registered nod_" in result.output
