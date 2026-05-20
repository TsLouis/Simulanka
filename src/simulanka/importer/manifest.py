"""Baseline manifest: declarative coverage map for a baseline's import.

Each baseline ships a ``simulanka_builds/manifest.yaml`` next to its
build_fns. The manifest declares:

* ``top_level.build`` — the build_fn returning the *full* top-level model
  (typically with ``example_inputs=None``, structure-only). Used as the
  mechanism-level guarantee of completeness: every nn.Module reachable from
  the top-level gets a node in the graph.
* ``children`` — a coverage map keyed by the fqn of each direct child of the
  top-level model. Each entry either supplies a focused ``build`` (a build_fn
  with real inputs for a dataflow trace) or ``skip: <reason>`` (an explicit
  waiver). Lint enforces ``set(children) == set(top_level.named_children())``
  so adding/removing a top-level child without updating the manifest fails
  loudly instead of silently leaving a component un-traced.

Top-level and focused traces are committed as **sibling** ``model`` nodes
under the same ``parent`` — the focused traces are not merged into the
top-level subtree.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from simulanka.importer.torch_export import ImportError as ModelImportError
from simulanka.importer.torch_export import import_model
from simulanka.layout.project import ProjectLayout


class ManifestError(RuntimeError):
    """Raised when the manifest is malformed or lint detects unresolved issues."""


class TopLevelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    build: str  # "pkg.module:fn"


class ChildSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    build: str | None = None
    skip: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> ChildSpec:
        if (self.build is None) == (self.skip is None):
            raise ValueError(
                "each child must specify exactly one of `build` or `skip` — "
                "use `build: pkg.module:fn` for a focused dataflow trace, "
                "or `skip: <reason>` to waive coverage."
            )
        return self


class BaselineManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_level: TopLevelSpec
    children: dict[str, ChildSpec] = Field(default_factory=dict)


@dataclass(frozen=True)
class LintIssue:
    severity: Literal["error", "warning"]
    message: str


@dataclass(frozen=True)
class BaselineImportSummary:
    top_level_node_id: str
    top_level_name: str
    child_node_ids: dict[str, str]  # child_fqn → committed model node id
    skipped: list[str] = field(default_factory=list)


def load_baseline_manifest(path: Path) -> BaselineManifest:
    """Load and validate ``manifest.yaml`` at ``path``."""
    import yaml

    if not path.exists():
        raise ManifestError(f"manifest not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ManifestError(f"malformed YAML in {path}: {exc}") from exc
    if raw is None:
        raise ManifestError(f"empty manifest: {path}")
    try:
        return BaselineManifest.model_validate(raw)
    except ValidationError as exc:
        raise ManifestError(f"invalid manifest {path}:\n{exc}") from exc


def _resolve_callable(spec: str) -> Callable[[], Any]:
    """Resolve ``pkg.module:function`` to the callable."""
    if ":" not in spec:
        raise ManifestError(f"build spec must be `pkg.module:function`; got {spec!r}.")
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ManifestError(
            f"build spec {spec!r}: module and attribute must both be non-empty."
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ManifestError(f"cannot import module {module_name!r}: {exc}") from exc
    try:
        fn = getattr(module, attr)
    except AttributeError as exc:
        raise ManifestError(f"{module_name!r} has no attribute {attr!r}.") from exc
    if not callable(fn):
        raise ManifestError(f"{spec!r} is not callable.")
    return fn  # type: ignore[no-any-return]


def lint_manifest(
    manifest: BaselineManifest, top_level_model: Any,
) -> list[LintIssue]:
    """Verify ``manifest.children`` covers exactly the direct children of the
    top-level model. No graph mutation, no build_fn calls for the children."""
    actual = {name for name, _ in top_level_model.named_children()}
    declared = set(manifest.children.keys())
    issues: list[LintIssue] = []
    missing = sorted(actual - declared)
    if missing:
        issues.append(LintIssue(
            severity="error",
            message=(
                f"manifest is missing coverage for children: {missing}. "
                "Each direct child of the top-level model must be listed under "
                "`children:` with either a `build` (focused dataflow trace) or "
                "`skip: <reason>` (explicit waiver)."
            ),
        ))
    unknown = sorted(declared - actual)
    if unknown:
        issues.append(LintIssue(
            severity="error",
            message=(
                f"manifest declares children that don't exist on the top-level "
                f"model: {unknown}. Top-level class is "
                f"{type(top_level_model).__name__}; its direct children are "
                f"{sorted(actual)}."
            ),
        ))
    return issues


def check_baseline(manifest_path: Path) -> list[LintIssue]:
    """Lint-only entry: instantiate the top-level via the manifest's build_fn
    and check coverage. Does not touch the graph."""
    manifest = load_baseline_manifest(manifest_path)
    top_model, _ = _instantiate_build(manifest.top_level.build, role="top_level")
    return lint_manifest(manifest, top_model)


def import_baseline(
    layout: ProjectLayout,
    manifest_path: Path,
    *,
    parent: str | None = None,
    actor: str = "importer:baseline",
) -> BaselineImportSummary:
    """Load, lint, and commit a baseline per its manifest.

    The top-level model is committed structure-only; each child entry with a
    ``build`` is committed as a sibling ``model`` node under the same parent,
    with a focused dataflow trace.
    """
    manifest = load_baseline_manifest(manifest_path)

    top_model, top_inputs = _instantiate_build(
        manifest.top_level.build, role="top_level",
    )

    issues = lint_manifest(manifest, top_model)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise ManifestError(
            "manifest lint failed:\n  - "
            + "\n  - ".join(i.message for i in errors),
        )

    top_name = type(top_model).__name__
    try:
        top_result = import_model(
            layout,
            _prebuilt(top_model, top_inputs),
            name=top_name,
            parent=parent,
            actor=actor,
        )
    except ModelImportError as exc:
        raise ManifestError(f"top_level import failed: {exc}") from exc

    child_ids: dict[str, str] = {}
    skipped: list[str] = []
    for fqn, spec in manifest.children.items():
        if spec.skip is not None:
            skipped.append(fqn)
            continue
        assert spec.build is not None  # ChildSpec validator guarantee
        sub_model, sub_inputs = _instantiate_build(
            spec.build, role=f"children[{fqn!r}]",
        )
        # Name the focused trace by the child's fqn (unique within the top-level
        # model by construction), not its class name — two children may share a
        # class (e.g. multiple Linear layers), which would collide as sibling
        # node names.
        try:
            sub_result = import_model(
                layout,
                _prebuilt(sub_model, sub_inputs),
                name=fqn,
                parent=parent,
                actor=actor,
            )
        except ModelImportError as exc:
            raise ManifestError(
                f"children[{fqn!r}] import failed: {exc}",
            ) from exc
        child_ids[fqn] = sub_result.model_node_id

    return BaselineImportSummary(
        top_level_node_id=top_result.model_node_id,
        top_level_name=top_name,
        child_node_ids=child_ids,
        skipped=skipped,
    )


def _prebuilt(
    model: Any, example_inputs: tuple[Any, ...] | None,
) -> Callable[[], tuple[Any, tuple[Any, ...] | None]]:
    """Wrap an already-instantiated model into a build_fn so we can feed it to
    ``import_model`` without rebuilding."""
    def _fn() -> tuple[Any, tuple[Any, ...] | None]:
        return model, example_inputs
    return _fn


def _instantiate_build(spec: str, *, role: str) -> tuple[Any, Any]:
    """Resolve and call a build_fn; check the return shape is
    ``(module, example_inputs_or_None)``."""
    fn = _resolve_callable(spec)
    try:
        built = fn()
    except Exception as exc:  # noqa: BLE001 — surface any build failure
        raise ManifestError(f"{role} build {spec!r} raised: {exc!r}") from exc
    if not (isinstance(built, tuple) and len(built) == 2):
        raise ManifestError(
            f"{role} build {spec!r} must return (model, example_inputs|None); "
            f"got {type(built).__name__}.",
        )
    return built[0], built[1]
