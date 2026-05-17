from __future__ import annotations

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

NODE_TYPES: dict[str, NodeTypeSpec] = {
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

EDGE_TYPES: dict[str, EdgeTypeSpec] = {
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

PORT_TYPES: frozenset[str] = frozenset({"any", "tensor", "scalar"})
