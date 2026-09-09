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

BUILTIN_PACKAGE = RegistryPackage(
    name="builtin",
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
        CapabilitySpec(
            key="trust_subject",
            consumers=frozenset({"context", "presentation"}),
            description="Receives research-domain trust and provenance presentation.",
        ),
    ),
    node_profiles=tuple(
        NodeProfileSpec(
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
        for key, legacy in _LEGACY_NODE_TYPES.items()
    ),
    edge_profiles=tuple(
        EdgeProfileSpec(
            key=key,
            needs_ports=legacy.needs_ports,
            source_profiles=legacy.source_node_types,
            target_profiles=legacy.target_node_types,
            source_port_direction=legacy.source_port_direction,
            target_port_direction=legacy.target_port_direction,
        )
        for key, legacy in _LEGACY_EDGE_TYPES.items()
    ),
    port_types=_LEGACY_PORT_TYPES,
)

DEFAULT_REGISTRY = Registry.build(version=2, packages=(BUILTIN_PACKAGE,))

# Compatibility facade for existing consumers. Registry v2 is authoritative;
# tasks 2.x migrate kernel and doctor injection before these names are retired.
NODE_TYPES: Mapping[str, NodeTypeSpec] = MappingProxyType(
    {
        key: NodeTypeSpec(name=key, allow_parents=profile.allow_parents)
        for key, profile in DEFAULT_REGISTRY.node_profiles.items()
    }
)
EDGE_TYPES: Mapping[str, EdgeTypeSpec] = MappingProxyType(
    {
        key: EdgeTypeSpec(
            name=key,
            needs_ports=profile.needs_ports,
            source_node_types=profile.source_profiles,
            target_node_types=profile.target_profiles,
            source_port_direction=profile.source_port_direction,
            target_port_direction=profile.target_port_direction,
        )
        for key, profile in DEFAULT_REGISTRY.edge_profiles.items()
    }
)
PORT_TYPES = DEFAULT_REGISTRY.port_types
