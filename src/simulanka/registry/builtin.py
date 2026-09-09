from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from simulanka.registry.profiles import (
    CapabilitySpec,
    EdgeProfileSpec,
    NodeProfileSpec,
    Registry,
    RegistryPackage,
)
from simulanka.registry.types import ANY, EdgeTypeSpec, NodeTypeSpec

# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------
#
# Structural (modeling) types: directory / model / module / file.
# Research-atom types (added in step 7): question / hypothesis / claim /
# evidence / experiment / run / note. Attrs conventions for atoms are
# documented in docs/design.md; the kernel does not strictly validate them
# (research fields churn frequently; a hard attrs schema would be friction).

_LEGACY_NODE_TYPES: dict[str, NodeTypeSpec] = {
    "directory": NodeTypeSpec(
        name="directory",
        allow_parents=frozenset({"directory", None}),
    ),
    "model": NodeTypeSpec(
        name="model",
        allow_parents=frozenset({"directory"}),
    ),
    "module": NodeTypeSpec(
        name="module",
        allow_parents=frozenset({"model", "module"}),
    ),
    "file": NodeTypeSpec(
        name="file",
        allow_parents=frozenset({"directory"}),
    ),
    # Research atoms
    "question": NodeTypeSpec(
        name="question",
        allow_parents=frozenset({"directory"}),
    ),
    "hypothesis": NodeTypeSpec(
        name="hypothesis",
        allow_parents=frozenset({"directory", "experiment"}),
    ),
    "claim": NodeTypeSpec(
        name="claim",
        allow_parents=frozenset({"directory", "experiment"}),
    ),
    "evidence": NodeTypeSpec(
        name="evidence",
        allow_parents=frozenset({"directory", "experiment", "run"}),
    ),
    "experiment": NodeTypeSpec(
        name="experiment",
        allow_parents=frozenset({"directory"}),
    ),
    "run": NodeTypeSpec(
        name="run",
        allow_parents=frozenset({"directory", "experiment"}),
    ),
    "note": NodeTypeSpec(
        name="note",
        allow_parents=frozenset({"directory", "experiment", "run"}),
    ),
    "task": NodeTypeSpec(
        name="task",
        allow_parents=frozenset({"directory", "experiment"}),
    ),
}

# ---------------------------------------------------------------------------
# Edge types
# ---------------------------------------------------------------------------

_LEGACY_EDGE_TYPES: dict[str, EdgeTypeSpec] = {
    "contains": EdgeTypeSpec(
        name="contains",
        needs_ports=False,
        # All container-capable types: structural containers + experiment + run
        # (run can contain evidence/notes that are scoped to that run).
        source_node_types=frozenset({"directory", "model", "module", "experiment", "run"}),
        target_node_types=frozenset({ANY}),
    ),
    "data_flow": EdgeTypeSpec(
        name="data_flow",
        needs_ports=True,
        source_node_types=frozenset({ANY}),
        target_node_types=frozenset({ANY}),
        source_port_direction="out",
        target_port_direction="in",
    ),
    # ---- Research semantic edges ----
    "addresses": EdgeTypeSpec(
        name="addresses",
        needs_ports=False,
        source_node_types=frozenset({"hypothesis"}),
        target_node_types=frozenset({"question"}),
    ),
    "tests": EdgeTypeSpec(
        name="tests",
        needs_ports=False,
        source_node_types=frozenset({"experiment", "run"}),
        target_node_types=frozenset({"hypothesis"}),
    ),
    "supports": EdgeTypeSpec(
        name="supports",
        needs_ports=False,
        source_node_types=frozenset({"evidence"}),
        target_node_types=frozenset({"claim", "hypothesis"}),
    ),
    "contradicts": EdgeTypeSpec(
        name="contradicts",
        needs_ports=False,
        source_node_types=frozenset({"evidence"}),
        target_node_types=frozenset({"claim", "hypothesis"}),
    ),
    "produces": EdgeTypeSpec(
        name="produces",
        needs_ports=False,
        source_node_types=frozenset({"run"}),
        target_node_types=frozenset({"file", "evidence"}),
    ),
    "part_of": EdgeTypeSpec(
        name="part_of",
        needs_ports=False,
        source_node_types=frozenset({"run"}),
        target_node_types=frozenset({"experiment"}),
    ),
    "uses": EdgeTypeSpec(
        name="uses",
        needs_ports=False,
        # A run uses a particular model (its imported structure) and one or
        # more config/code files. The edge is intentionally permissive on
        # target side because configs may be modeled later as their own type.
        source_node_types=frozenset({"run"}),
        target_node_types=frozenset({"model", "file"}),
    ),
    "fulfills": EdgeTypeSpec(
        name="fulfills",
        needs_ports=False,
        source_node_types=frozenset({"run"}),
        target_node_types=frozenset({"task"}),
    ),
}

_LEGACY_PORT_TYPES = frozenset({"any", "tensor", "scalar"})

_CONTAINER_TYPES = frozenset({"directory", "model", "module", "experiment", "run"})
_TRUST_SUBJECT_TYPES = frozenset(
    {"hypothesis", "claim", "experiment", "task", "run", "evidence", "note"}
)


def _node_profile(key: str) -> NodeProfileSpec:
    legacy = _LEGACY_NODE_TYPES[key]
    return NodeProfileSpec(
        key=key,
        capabilities=frozenset(
            {
                "contextualizable",
                "renamable",
                "deletable",
                *(("container",) if key in _CONTAINER_TYPES else ()),
                *(("trust_subject",) if key in _TRUST_SUBJECT_TYPES else ()),
            }
        ),
        allow_parents=legacy.allow_parents,
    )


def _edge_profile(key: str) -> EdgeProfileSpec:
    legacy = _LEGACY_EDGE_TYPES[key]
    return EdgeProfileSpec(
        key=key,
        needs_ports=legacy.needs_ports,
        source_profiles=legacy.source_node_types,
        target_profiles=legacy.target_node_types,
        source_port_direction=legacy.source_port_direction,
        target_port_direction=legacy.target_port_direction,
    )


CORE_PACKAGE = RegistryPackage(
    name="core",
    capabilities=(
        CapabilitySpec(
            key="container",
            consumers=frozenset({"validation", "action"}),
            description="May contain child nodes subject to profile parent rules.",
        ),
        CapabilitySpec(
            key="contextualizable",
            consumers=frozenset({"context", "action"}),
            description="May be attached to an agent session as explicit context.",
        ),
        CapabilitySpec(
            key="renamable",
            consumers=frozenset({"action"}),
            description="May be a rename candidate before actor and state policy.",
        ),
        CapabilitySpec(
            key="deletable",
            consumers=frozenset({"action"}),
            description="May be a delete candidate before actor and state policy.",
        ),
    ),
    edge_profiles=(
        EdgeProfileSpec(
            key="contains",
            needs_ports=False,
            source_capabilities=frozenset({"container"}),
            target_profiles=frozenset({ANY}),
        ),
        _edge_profile("data_flow"),
    ),
    port_types=frozenset({"any"}),
)

FILESYSTEM_PACKAGE = RegistryPackage(
    name="filesystem",
    node_profiles=tuple(_node_profile(key) for key in ("directory", "file")),
)

ML_TORCH_PACKAGE = RegistryPackage(
    name="ml-torch",
    node_profiles=tuple(_node_profile(key) for key in ("model", "module")),
    port_types=frozenset({"tensor", "scalar"}),
)

RESEARCH_PACKAGE = RegistryPackage(
    name="research",
    capabilities=(
        CapabilitySpec(
            key="trust_subject",
            consumers=frozenset({"context", "presentation"}),
            description="Receives research-domain trust and provenance presentation.",
        ),
    ),
    node_profiles=tuple(
        _node_profile(key)
        for key in (
            "question",
            "hypothesis",
            "claim",
            "evidence",
            "experiment",
            "note",
            "task",
        )
    ),
    edge_profiles=tuple(
        _edge_profile(key)
        for key in (
            "addresses",
            "tests",
            "supports",
            "contradicts",
        )
    ),
)


RUNTIME_PACKAGE = RegistryPackage(
    name="runtime",
    node_profiles=(_node_profile("run"),),
    edge_profiles=tuple(
        _edge_profile(key) for key in ("produces", "part_of", "uses", "fulfills")
    ),
)

BUILTIN_PACKAGES = (
    CORE_PACKAGE,
    FILESYSTEM_PACKAGE,
    ML_TORCH_PACKAGE,
    RESEARCH_PACKAGE,
    RUNTIME_PACKAGE,
)


def _aggregate_packages(
    name: str,
    packages: tuple[RegistryPackage, ...],
) -> RegistryPackage:
    return RegistryPackage(
        name=name,
        capabilities=tuple(item for package in packages for item in package.capabilities),
        node_profiles=tuple(item for package in packages for item in package.node_profiles),
        edge_profiles=tuple(item for package in packages for item in package.edge_profiles),
        port_types=frozenset(
            item for package in packages for item in package.port_types
        ),
        presentations=tuple(
            item for package in packages for item in package.presentations
        ),
        templates=tuple(item for package in packages for item in package.templates),
        aliases=tuple(item for package in packages for item in package.aliases),
        validators={
            key: validator
            for package in packages
            for key, validator in package.validators.items()
        },
    )


# Transitional aggregate for extension code written before built-ins were split.
BUILTIN_PACKAGE = _aggregate_packages("builtin", BUILTIN_PACKAGES)

DEFAULT_REGISTRY = Registry.build(version=2, packages=BUILTIN_PACKAGES)

# Compatibility facade for existing consumers. Registry v2 is authoritative;
# old maps preserve their exact v1 shape while runtime consumers use Registry.
NODE_TYPES: Mapping[str, NodeTypeSpec] = MappingProxyType(dict(_LEGACY_NODE_TYPES))
EDGE_TYPES: Mapping[str, EdgeTypeSpec] = MappingProxyType(dict(_LEGACY_EDGE_TYPES))
PORT_TYPES = _LEGACY_PORT_TYPES
