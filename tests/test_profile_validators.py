from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import CreateNodeOp, UpdateAttrsOp
from simulanka.kernel.manifest import load_manifest
from simulanka.kernel.validator import ValidationError
from simulanka.layout.project import init_project
from simulanka.registry import (
    NodeProfileSpec,
    ProfileEntityView,
    ProfileValidationOp,
    ProfileValidationView,
    Registry,
    RegistryPackage,
)
from simulanka.storage.entity_store import iter_nodes, load_node, save_node


def _validator_registry(
    observations: list[tuple[str, bool, bool, bool]],
) -> Registry:
    def require_ready(
        view: ProfileValidationView,
        op: ProfileValidationOp,
    ) -> tuple[str, ...]:
        candidate_visible = view.nodes.get(op.entity.id) == op.entity
        view_mutation_blocked = False
        attrs_mutation_blocked = False
        nested_mutation_blocked = False
        try:
            cast(dict[str, ProfileEntityView], view.nodes)[op.entity.id] = op.entity
        except TypeError:
            view_mutation_blocked = True
        try:
            cast(dict[str, Any], op.entity.attrs)["validator_was_here"] = True
        except TypeError:
            attrs_mutation_blocked = True
        nested = op.entity.attrs.get("nested")
        if nested is not None:
            try:
                cast(dict[str, Any], nested)["changed"] = True
            except TypeError:
                nested_mutation_blocked = True
        observations.append(
            (
                op.kind,
                candidate_visible,
                view_mutation_blocked and attrs_mutation_blocked,
                nested_mutation_blocked,
            )
        )
        if op.entity.attrs.get("status") != "ready":
            return ("status must be ready",)
        return ()

    package = RegistryPackage(
        name="validator-test",
        node_profiles=(
            NodeProfileSpec(
                key="validated.service",
                allow_parents=frozenset({None}),
                attrs_fields={"status": "string", "nested": "object"},
                validator="require-ready",
            ),
            NodeProfileSpec(
                key="closed.record",
                allow_parents=frozenset({None}),
                attrs_fields={"status": "string"},
                closed_attrs=True,
            ),
        ),
        validators={"require-ready": require_ready},
    )
    return Registry.build(version=2, packages=(package,))


def test_attrs_contract_is_open_by_default_and_can_be_closed(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    registry = _validator_registry([])

    node_id = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(
                type="validated.service",
                name="open",
                attrs={"status": "ready", "extension_field": "accepted"},
            )
        ],
        actor="user",
        registry=registry,
    ).nodes[0]
    assert load_node(layout, node_id).attrs["extension_field"] == "accepted"

    with pytest.raises(ValidationError, match="unknown attrs"):
        apply_patch_now(
            layout,
            ops=[
                CreateNodeOp(
                    type="closed.record",
                    name="closed",
                    attrs={"status": "ready", "extension_field": "rejected"},
                )
            ],
            actor="user",
            registry=registry,
        )


def test_profile_validator_is_read_only_atomic_and_shared_with_doctor(
    tmp_path: Path,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    observations: list[tuple[str, bool, bool, bool]] = []
    registry = _validator_registry(observations)
    graph_version = load_manifest(layout).graph_version

    with pytest.raises(ValidationError, match="status must be ready"):
        apply_patch_now(
            layout,
            ops=[
                CreateNodeOp(
                    type="validated.service",
                    name="invalid",
                    attrs={"status": "blocked"},
                )
            ],
            actor="user",
            registry=registry,
        )
    assert list(iter_nodes(layout)) == []
    assert load_manifest(layout).graph_version == graph_version

    node_id = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(
                type="validated.service",
                name="valid",
                attrs={"status": "ready", "nested": {"changed": False}},
            )
        ],
        actor="user",
        registry=registry,
    ).nodes[0]
    stored = load_node(layout, node_id)
    assert stored.attrs == {"status": "ready", "nested": {"changed": False}}

    with pytest.raises(ValidationError, match="status must be ready"):
        apply_patch_now(
            layout,
            ops=[UpdateAttrsOp(target=node_id, attrs={"status": "blocked"})],
            actor="user",
            registry=registry,
        )
    assert load_node(layout, node_id) == stored

    save_node(
        layout,
        stored.model_copy(update={"attrs": {"status": "blocked"}}),
    )
    report = run_doctor(layout, registry=registry)
    assert "profile_validator_failed" in {issue.code for issue in report.issues}

    assert [observation[0] for observation in observations] == [
        "create",
        "create",
        "update",
        "doctor",
    ]
    assert all(observation[1] for observation in observations)
    assert all(observation[2] for observation in observations)
    assert observations[1][3]
    assert "validator_was_here" not in load_node(layout, node_id).attrs
