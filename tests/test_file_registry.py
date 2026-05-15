from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from simulanka.cli.app import app
from simulanka.kernel.doctor import run_doctor
from simulanka.layout.file_registry import (
    FileRegistryError,
    create_file,
    register_file,
)
from simulanka.layout.project import init_project


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
