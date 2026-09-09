from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from simulanka.registry import (
    BUILTIN_PACKAGES,
    DEFAULT_REGISTRY,
    EDGE_TYPES,
    NODE_TYPES,
    PORT_TYPES,
    SOFTWARE_SERVICE_PACKAGE,
    AliasSpec,
    CapabilitySpec,
    EdgeProfileSpec,
    NodeProfileSpec,
    PresentationSpec,
    Registry,
    RegistryBuildError,
    RegistryPackage,
    TemplatePortSpec,
    TemplateSpec,
)


def _validator(_view: object, _op: object) -> tuple[str, ...]:
    return ()


def _composable_package() -> RegistryPackage:
    return RegistryPackage(
        name="composition-test",
        capabilities=(
            CapabilitySpec("contextualizable", frozenset({"context"})),
            CapabilitySpec("assertion_like", frozenset({"validation", "presentation"})),
        ),
        node_profiles=(
            NodeProfileSpec(
                key="base",
                capabilities=frozenset({"contextualizable"}),
                allow_parents=frozenset({None}),
                attrs_fields={"title": "string"},
                validator="base-validator",
                presentation="base-card",
            ),
            NodeProfileSpec(
                key="child",
                extends="base",
                capabilities=frozenset({"assertion_like"}),
                attrs_fields={"score": "number"},
                validator="child-validator",
            ),
        ),
        edge_profiles=(
            EdgeProfileSpec(
                key="supports",
                needs_ports=False,
                source_profiles=frozenset({"legacy-child"}),
                target_profiles=frozenset({"base"}),
                source_capabilities=frozenset({"assertion_like"}),
            ),
        ),
        port_types=frozenset({"scalar"}),
        presentations=(
            PresentationSpec(
                key="base-card",
                category="Test",
                card_fields=("title", "score"),
            ),
        ),
        templates=(
            TemplateSpec(
                key="child.default",
                profile="legacy-child",
                name="Child",
                category="Test",
                default_attrs={"nested": {"enabled": True}},
                default_ports=(
                    TemplatePortSpec(name="value", direction="out", port_type="number"),
                ),
            ),
        ),
        aliases=(
            AliasSpec(kind="node", alias="old-child", target="legacy-child"),
            AliasSpec(kind="node", alias="legacy-child", target="child"),
            AliasSpec(kind="port", alias="number", target="scalar"),
        ),
        validators={"base-validator": _validator, "child-validator": _validator},
    )


def test_registry_resolves_inheritance_aliases_and_descriptor_deterministically() -> None:
    package = _composable_package()

    first = Registry.build(version=2, packages=(package,))
    second = Registry.build(version=2, packages=(package,))

    child = first.node("old-child")
    assert child is not None
    assert child.lineage == ("base", "child")
    assert child.capabilities == frozenset({"contextualizable", "assertion_like"})
    assert child.allow_parents == frozenset({None})
    assert child.attrs_fields == {"title": "string", "score": "number"}
    assert child.validator_chain == ("base-validator", "child-validator")
    assert child.presentation == "base-card"
    assert first.resolve_node_key("legacy-child") == "child"
    assert first.resolve_port_key("number") == "scalar"
    assert first.templates["child.default"].profile == "child"
    assert first.templates["child.default"].default_ports[0].port_type == "scalar"

    edge = first.edge("supports")
    assert edge is not None
    assert edge.source_profiles == frozenset({"child"})
    assert edge.accepts_source(child)
    assert edge.accepts_target(first.node_profiles["base"])

    assert first.descriptor_digest == second.descriptor_digest
    assert len(first.descriptor_digest) == 64
    descriptor = first.descriptor()
    assert descriptor["digest"] == first.descriptor_digest
    assert json.loads(json.dumps(descriptor))["version"] == 2


def test_registry_and_nested_template_defaults_are_runtime_immutable() -> None:
    registry = Registry.build(version=2, packages=(_composable_package(),))

    with pytest.raises(TypeError):
        cast(dict[str, Any], registry.node_profiles)["other"] = registry.node_profiles["base"]

    defaults = cast(dict[str, Any], registry.templates["child.default"].default_attrs)
    with pytest.raises(TypeError):
        defaults["nested"] = {}
    nested = cast(dict[str, Any], defaults["nested"])
    with pytest.raises(TypeError):
        nested["enabled"] = False


def test_registry_fails_closed_for_duplicate_and_invalid_references() -> None:
    duplicate = RegistryPackage(
        name="duplicate",
        node_profiles=(NodeProfileSpec(key="base"),),
    )
    with pytest.raises(RegistryBuildError, match="'composition-test' and 'duplicate'"):
        Registry.build(version=2, packages=(_composable_package(), duplicate))

    unknown_base = RegistryPackage(
        name="unknown-base",
        node_profiles=(NodeProfileSpec(key="child", extends="missing"),),
    )
    with pytest.raises(RegistryBuildError, match="Unknown node base 'missing'"):
        Registry.build(version=2, packages=(unknown_base,))

    cyclic = RegistryPackage(
        name="cyclic",
        node_profiles=(
            NodeProfileSpec(key="a", extends="b"),
            NodeProfileSpec(key="b", extends="a"),
        ),
    )
    with pytest.raises(RegistryBuildError, match="inheritance cycle"):
        Registry.build(version=2, packages=(cyclic,))

    unknown_capability = RegistryPackage(
        name="unknown-capability",
        node_profiles=(
            NodeProfileSpec(key="node", capabilities=frozenset({"decorative-blue"})),
        ),
    )
    with pytest.raises(RegistryBuildError, match="unknown capabilities"):
        Registry.build(version=2, packages=(unknown_capability,))

    dangling = RegistryPackage(
        name="dangling",
        node_profiles=(
            NodeProfileSpec(
                key="node",
                presentation="missing-card",
                validator="missing-validator",
            ),
        ),
    )
    with pytest.raises(RegistryBuildError, match="unknown validator"):
        Registry.build(version=2, packages=(dangling,))


def test_registry_rejects_consumerless_capability_and_alias_cycles() -> None:
    with pytest.raises(RegistryBuildError, match="must have a validation"):
        CapabilitySpec(key="just-blue", consumers=frozenset())

    package = RegistryPackage(
        name="alias-cycle",
        node_profiles=(NodeProfileSpec(key="node"),),
        aliases=(
            AliasSpec(kind="node", alias="a", target="b"),
            AliasSpec(kind="node", alias="b", target="a"),
        ),
    )
    with pytest.raises(RegistryBuildError, match="alias cycle"):
        Registry.build(version=2, packages=(package,))


def test_builtin_compatibility_facade_preserves_v1_contract() -> None:
    assert DEFAULT_REGISTRY.version == 2
    assert set(NODE_TYPES) == {
        "directory",
        "model",
        "module",
        "file",
        "question",
        "hypothesis",
        "claim",
        "evidence",
        "experiment",
        "run",
        "note",
        "task",
    }
    assert set(EDGE_TYPES) == {
        "contains",
        "data_flow",
        "addresses",
        "tests",
        "supports",
        "contradicts",
        "produces",
        "part_of",
        "uses",
        "fulfills",
    }
    assert sorted(PORT_TYPES) == ["any", "scalar", "tensor"]
    assert NODE_TYPES["module"].allow_parents == frozenset({"model", "module"})
    assert EDGE_TYPES["data_flow"].needs_ports
    assert EDGE_TYPES["data_flow"].source_port_direction == "out"
    assert EDGE_TYPES["data_flow"].target_port_direction == "in"
    assert EDGE_TYPES["supports"].source_node_types == frozenset({"evidence"})
    assert isinstance(NODE_TYPES, Mapping)

    with pytest.raises(TypeError):
        cast(dict[str, Any], NODE_TYPES)["service"] = NODE_TYPES["module"]


def test_default_registry_composes_explicit_builtin_domain_packages() -> None:
    assert DEFAULT_REGISTRY.packages == (
        "core",
        "filesystem",
        "ml-torch",
        "research",
        "runtime",
    )
    assert DEFAULT_REGISTRY.descriptor_digest == Registry.build(
        version=2,
        packages=BUILTIN_PACKAGES,
    ).descriptor_digest

    package_nodes = {
        package.name: {profile.key for profile in package.node_profiles}
        for package in BUILTIN_PACKAGES
    }
    package_edges = {
        package.name: {profile.key for profile in package.edge_profiles}
        for package in BUILTIN_PACKAGES
    }
    assert package_nodes == {
        "core": set(),
        "filesystem": {"directory", "file"},
        "ml-torch": {"model", "module"},
        "research": {
            "question",
            "hypothesis",
            "claim",
            "evidence",
            "experiment",
            "note",
            "task",
        },
        "runtime": {"run"},
    }
    assert package_edges == {
        "core": {"contains", "data_flow"},
        "filesystem": set(),
        "ml-torch": set(),
        "research": {"addresses", "tests", "supports", "contradicts"},
        "runtime": {"produces", "part_of", "uses", "fulfills"},
    }
    contains = DEFAULT_REGISTRY.edge_profiles["contains"]
    assert contains.source_profiles == frozenset({"*"})
    assert contains.source_capabilities == frozenset({"container"})


def test_torch_catalog_is_templates_not_profiles() -> None:
    profile_keys = set(DEFAULT_REGISTRY.node_profiles)
    template_keys = set(DEFAULT_REGISTRY.templates)

    assert {"Conv2d", "Linear", "cat"}.isdisjoint(profile_keys)
    assert {
        "torch.nn.Conv2d",
        "torch.nn.Linear",
        "torch.cat",
        "module.blank",
        "module.container",
        "model.container",
        "filesystem.directory",
    } <= template_keys
    assert len(template_keys) == 49

    conv = DEFAULT_REGISTRY.templates["torch.nn.Conv2d"]
    assert conv.profile == "module"
    assert conv.name == "conv2d"
    assert conv.default_attrs == {
        "class_name": "Conv2d",
        "class_module": "torch.nn",
    }
    assert [(port.name, port.direction, port.port_type) for port in conv.default_ports] == [
        ("input", "in", "tensor"),
        ("output", "out", "tensor"),
    ]

    cat = DEFAULT_REGISTRY.templates["torch.cat"]
    assert cat.profile == "module"
    assert cat.default_attrs["class_module"] == "torch"
    assert [port.name for port in cat.default_ports] == ["a", "b", "output"]


def test_runtime_consumers_do_not_depend_on_legacy_global_type_maps() -> None:
    source_root = Path(__file__).parents[1] / "src" / "simulanka"
    legacy_names = ("NODE_TYPES", "EDGE_TYPES", "PORT_TYPES")
    offenders = [
        str(path.relative_to(source_root))
        for package in ("kernel", "cli", "importer", "server")
        for path in sorted((source_root / package).rglob("*.py"))
        if any(name in path.read_text("utf-8") for name in legacy_names)
    ]
    assert offenders == []


def test_software_service_package_extends_registry_without_core_branches() -> None:
    registry = Registry.build(
        version=2,
        packages=(*BUILTIN_PACKAGES, SOFTWARE_SERVICE_PACKAGE),
    )

    service = registry.node("software.service")
    assert service is not None
    assert service.capabilities >= {
        "contextualizable",
        "renamable",
        "deletable",
        "deployable",
    }
    assert service.accepts_parent("directory")
    assert registry.node("service") is None

    dependency = registry.edge("software.depends_on")
    assert dependency is not None
    assert dependency.accepts_source(service)
    assert dependency.accepts_target(service)

    template = registry.templates["software.http-service"]
    assert template.profile == "software.service"
    assert template.default_attrs["runtime"] == "python"
    assert registry.presentations[service.presentation or ""].icon == "server"

    assert "software.service" not in DEFAULT_REGISTRY.node_profiles
    assert "software.depends_on" not in DEFAULT_REGISTRY.edge_profiles
