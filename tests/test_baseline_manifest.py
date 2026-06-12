"""Tests for the baseline-manifest layer (load + lint + import orchestrator).

Synthetic ``nn.Module`` fixtures are pickle-unfriendly when defined at function
scope; module-scope keeps them simple and reusable across tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

torch = pytest.importorskip("torch")

import torch.nn as nn  # noqa: E402

from simulanka.importer import (  # noqa: E402
    BaselineManifest,
    ManifestError,
    check_baseline,
    import_baseline,
    lint_manifest,
    load_baseline_manifest,
)
from simulanka.importer.manifest import ChildSpec  # noqa: E402
from simulanka.kernel.apply import apply_patch  # noqa: E402
from simulanka.kernel.doctor import run_doctor  # noqa: E402
from simulanka.kernel.intent import CreateNodeOp, PatchIntent  # noqa: E402
from simulanka.layout.project import ProjectLayout, init_project  # noqa: E402


class _Top(nn.Module):
    """Top-level model with three direct children: encoder, head, tail."""

    def __init__(self) -> None:
        super().__init__()
        self.encoder = nn.Linear(8, 8)
        self.head = nn.Linear(8, 2)
        self.tail = nn.Linear(2, 1)

    def forward(self, batch: dict[str, Any]) -> Any:  # not called
        return self.tail(self.head(self.encoder(batch["x"])))


def build_top() -> tuple[nn.Module, None]:
    return _Top(), None


def build_encoder() -> tuple[nn.Module, tuple[Any, ...]]:
    return nn.Linear(8, 8), (torch.randn(2, 8),)


def build_head() -> tuple[nn.Module, tuple[Any, ...]]:
    return nn.Linear(8, 2), (torch.randn(2, 8),)


def _make_directory(layout: ProjectLayout, name: str, parent: str | None = None) -> None:
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name=name, parent=parent)],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_child_spec_requires_exactly_one_of_build_or_skip() -> None:
    """ChildSpec.build XOR ChildSpec.skip — both or neither is a validation error."""
    with pytest.raises(ValueError, match="exactly one"):
        ChildSpec()
    with pytest.raises(ValueError, match="exactly one"):
        ChildSpec(build="pkg:fn", skip="redundant")


def test_load_baseline_manifest_round_trip(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        """\
top_level:
  build: tests.test_baseline_manifest:build_top
children:
  encoder:
    build: tests.test_baseline_manifest:build_encoder
  head:
    build: tests.test_baseline_manifest:build_head
    note: focused trace
  tail:
    skip: single Linear, dataflow trivial
""",
    )
    manifest = load_baseline_manifest(manifest_path)
    assert manifest.top_level.build.endswith(":build_top")
    assert set(manifest.children) == {"encoder", "head", "tail"}
    assert manifest.children["tail"].skip is not None
    assert manifest.children["head"].note == "focused trace"


def test_load_baseline_manifest_rejects_extra_fields(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        """\
top_level:
  build: x:y
mystery_field: 42
""",
    )
    with pytest.raises(ManifestError, match="Extra inputs"):
        load_baseline_manifest(manifest_path)


def test_load_baseline_manifest_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not found"):
        load_baseline_manifest(tmp_path / "absent.yaml")


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

def _manifest_with_children(**children: ChildSpec) -> BaselineManifest:
    return BaselineManifest.model_validate({
        "top_level": {"build": "tests.test_baseline_manifest:build_top"},
        "children": {k: v.model_dump(exclude_none=True) for k, v in children.items()},
    })


def test_lint_passes_when_coverage_matches_named_children() -> None:
    manifest = _manifest_with_children(
        encoder=ChildSpec(build="tests.test_baseline_manifest:build_encoder"),
        head=ChildSpec(skip="trivial"),
        tail=ChildSpec(skip="trivial"),
    )
    assert lint_manifest(manifest, _Top()) == []


def test_lint_flags_missing_child() -> None:
    manifest = _manifest_with_children(
        encoder=ChildSpec(build="tests.test_baseline_manifest:build_encoder"),
        head=ChildSpec(skip="trivial"),
        # `tail` is intentionally absent
    )
    issues = lint_manifest(manifest, _Top())
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "tail" in issues[0].message
    assert "missing coverage" in issues[0].message


def test_lint_flags_unknown_child() -> None:
    manifest = _manifest_with_children(
        encoder=ChildSpec(build="tests.test_baseline_manifest:build_encoder"),
        head=ChildSpec(skip="trivial"),
        tail=ChildSpec(skip="trivial"),
        ghost=ChildSpec(skip="not on the model"),
    )
    issues = lint_manifest(manifest, _Top())
    assert any("ghost" in i.message for i in issues)


def test_check_baseline_lint_only_does_not_mutate_graph(tmp_path: Path) -> None:
    """``check_baseline`` must not require a ProjectLayout — it's a pure lint."""
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        """\
top_level:
  build: tests.test_baseline_manifest:build_top
children:
  encoder: {build: tests.test_baseline_manifest:build_encoder}
  head: {skip: trivial}
  tail: {skip: trivial}
""",
    )
    assert check_baseline(manifest_path) == []


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def test_import_baseline_commits_top_level_and_focused_traces(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        """\
top_level:
  build: tests.test_baseline_manifest:build_top
children:
  encoder:
    build: tests.test_baseline_manifest:build_encoder
  head:
    build: tests.test_baseline_manifest:build_head
  tail:
    skip: single Linear, dataflow trivial
""",
    )

    project = init_project(tmp_path / "proj", with_scaffold=False).layout
    _make_directory(project, "models")

    summary = import_baseline(project, manifest_path, parent="/models")

    # Top-level node + 2 focused traces committed, 1 child skipped.
    assert summary.top_level_name == "_Top"
    assert set(summary.child_node_ids) == {"encoder", "head"}
    assert summary.skipped == ["tail"]

    # Doctor still passes.
    report = run_doctor(project)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_import_baseline_fails_loudly_on_missing_coverage(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        """\
top_level:
  build: tests.test_baseline_manifest:build_top
children:
  encoder:
    build: tests.test_baseline_manifest:build_encoder
  head:
    skip: trivial
""",
    )

    project = init_project(tmp_path / "proj", with_scaffold=False).layout
    _make_directory(project, "models")

    with pytest.raises(ManifestError, match="tail"):
        import_baseline(project, manifest_path, parent="/models")


def test_cli_import_baseline_defaults_to_baselines_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitting --parent places the import under the scaffold's /baselines."""
    from typer.testing import CliRunner

    from simulanka.cli.app import app
    from simulanka.kernel.resolver import resolve_node

    builds = tmp_path / "baseline" / "simulanka_builds"
    builds.mkdir(parents=True)
    (builds / "manifest.yaml").write_text(
        """\
top_level:
  build: tests.test_baseline_manifest:build_top
children:
  encoder: {build: tests.test_baseline_manifest:build_encoder}
  head: {skip: trivial}
  tail: {skip: trivial}
""",
        encoding="utf-8",
    )

    project = init_project(tmp_path / "proj").layout  # scaffold creates /baselines
    monkeypatch.setenv("SIMULANKA_PROJECT", str(project.root))

    result = CliRunner().invoke(app, ["import", "baseline", str(tmp_path / "baseline")])
    assert result.exit_code == 0, result.output
    top = resolve_node(project, "/baselines/_Top")
    assert top.type == "model"
