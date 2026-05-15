from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from simulanka.cli.app import app
from simulanka.layout import ProjectLayout, init_project


def test_init_creates_full_tree(tmp_path: Path) -> None:
    result = init_project(tmp_path)

    assert result.status == "created"
    layout = result.layout
    for d in (
        layout.dot_dir,
        layout.graph_dir,
        layout.nodes_dir,
        layout.edges_dir,
        layout.ports_dir,
        layout.events_dir,
        layout.indexes_dir,
        layout.logs_dir,
        layout.cache_dir,
    ):
        assert d.is_dir(), f"missing dir: {d}"

    assert layout.manifest_path.is_file()
    payload = json.loads(layout.manifest_path.read_text("utf-8"))
    # scaffold-on default commits one patch creating the managed-dir nodes.
    assert payload["graph_version"] == 1
    assert payload["project_id"].startswith("prj_")
    assert payload["content_hash"].startswith("sha256:")

    assert (layout.dot_dir / ".gitignore").is_file()

    # Managed top-level directories should exist on disk.
    for dir_name in ("src", "tests", "docs", "papers", "baselines"):
        assert (layout.root / dir_name).is_dir(), f"missing managed dir: {dir_name}"
    assert (layout.dot_dir / "artifacts").is_dir()


def test_init_is_idempotent(tmp_path: Path) -> None:
    first = init_project(tmp_path)
    second = init_project(tmp_path)

    assert first.status == "created"
    assert second.status == "already_initialized"
    assert first.manifest.project_id == second.manifest.project_id


def test_discover_finds_project_from_subdirectory(tmp_path: Path) -> None:
    init_project(tmp_path)
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)

    found = ProjectLayout.discover(start=nested)

    assert found is not None
    assert found.root == tmp_path.resolve()


def test_discover_returns_none_when_absent(tmp_path: Path) -> None:
    assert ProjectLayout.discover(start=tmp_path) is None


def test_cli_init_command(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "demo"
    result = runner.invoke(app, ["init", str(target)])

    assert result.exit_code == 0, result.output
    assert "Initialized Simulanka project" in result.output
    assert (target / ".simulanka" / "manifest.json").is_file()

    again = runner.invoke(app, ["init", str(target)])
    assert again.exit_code == 0
    assert "Already initialized" in again.output
