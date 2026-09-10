from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from simulanka.registry.profiles import (
    ActionExecutorSpec,
    ActionSpec,
    CapabilitySpec,
    EdgeProfileSpec,
    NodeProfileSpec,
    PresentationSpec,
    RefSetPredicate,
    Registry,
    RegistryPackage,
    TemplatePortSpec,
    TemplateSpec,
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

_PRESENTATIONS = {
    item.key: item
    for item in (
        PresentationSpec(
            key="directory",
            category="结构",
            palette_token="directory",
            icon="folder",
            inspector_fields=("fs_path",),
        ),
        PresentationSpec(
            key="file",
            category="结构",
            palette_token="file",
            icon="file",
            inspector_fields=("path", "kind", "content_hash"),
        ),
        PresentationSpec(
            key="model",
            category="模型",
            palette_token="model",
            icon="model",
            card_fields=("class_name", "num_params"),
            inspector_fields=("class_name", "num_params", "source_file"),
            formatters={"class_name": "mono", "num_params": "integer"},
        ),
        PresentationSpec(
            key="module",
            category="模型",
            palette_token="module",
            icon="module",
            card_fields=("class_name", "num_params"),
            inspector_fields=("class_name", "class_module", "num_params", "source_file"),
            formatters={"class_name": "mono", "num_params": "integer"},
        ),
        PresentationSpec(
            key="question",
            category="研究",
            palette_token="question",
            icon="question",
            card_fields=("body",),
            inspector_fields=("body",),
            formatters={"body": "text"},
        ),
        PresentationSpec(
            key="hypothesis",
            category="研究",
            palette_token="hypothesis",
            icon="hypothesis",
            card_fields=("body",),
            inspector_fields=("body", "verdict"),
            badges=("verdict",),
            formatters={"body": "text", "verdict": "status"},
        ),
        PresentationSpec(
            key="claim",
            category="研究",
            palette_token="claim",
            icon="claim",
            card_fields=("body",),
            inspector_fields=("body", "status"),
            badges=("status",),
            formatters={"body": "text", "status": "status"},
        ),
        PresentationSpec(
            key="evidence",
            category="研究",
            palette_token="evidence",
            icon="evidence",
            card_fields=("metrics", "body"),
            inspector_fields=("metrics", "body"),
            formatters={"metrics": "metrics", "body": "text"},
        ),
        PresentationSpec(
            key="experiment",
            category="研究",
            palette_token="experiment",
            icon="experiment",
            card_fields=("goal",),
            inspector_fields=("goal", "status"),
            badges=("status",),
            formatters={"goal": "text", "status": "status"},
        ),
        PresentationSpec(
            key="note",
            category="研究",
            palette_token="note",
            icon="note",
            card_fields=("body",),
            inspector_fields=("body", "kind", "status"),
            badges=("kind", "status"),
            formatters={"body": "text", "kind": "status", "status": "status"},
        ),
        PresentationSpec(
            key="task",
            category="研究",
            palette_token="task",
            icon="task",
            card_fields=("goal", "allowed_outputs", "acceptance_command"),
            inspector_fields=(
                "goal",
                "status",
                "acceptance_command",
                "allowed_outputs",
                "budget_time_seconds",
            ),
            badges=("status", "budget_time_seconds"),
            formatters={
                "goal": "text",
                "status": "status",
                "budget_time_seconds": "duration",
                "allowed_outputs": "count",
                "acceptance_command": "command",
            },
        ),
        PresentationSpec(
            key="run",
            category="运行",
            palette_token="run",
            icon="run",
            card_fields=("duration_seconds", "exit_code"),
            inspector_fields=(
                "status",
                "duration_seconds",
                "exit_code",
                "stdout_path",
                "stderr_path",
                "metrics_path",
            ),
            badges=("status", "contract_check.status"),
            formatters={
                "status": "status",
                "contract_check.status": "status",
                "duration_seconds": "duration",
                "exit_code": "exit-code",
            },
        ),
    )
}


def _node_profile(key: str) -> NodeProfileSpec:
    legacy = _LEGACY_NODE_TYPES[key]
    capabilities = {"contextualizable"}
    if key not in {"directory", "file"}:
        capabilities.add("renamable")
    if key in {"model", "module"}:
        capabilities.add("deletable")
    if key in _CONTAINER_TYPES:
        capabilities.add("container")
    if key in _TRUST_SUBJECT_TYPES:
        capabilities.add("trust_subject")
    return NodeProfileSpec(
        key=key,
        capabilities=frozenset(capabilities),
        allow_parents=legacy.allow_parents,
        presentation=key,
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


def _tensor_ports(*input_names: str) -> tuple[TemplatePortSpec, ...]:
    return (
        *(TemplatePortSpec(name=name, direction="in", port_type="tensor") for name in input_names),
        TemplatePortSpec(name="output", direction="out", port_type="tensor"),
    )


def _torch_nn_template(
    category: str,
    class_name: str,
    input_names: tuple[str, ...] = ("input",),
) -> TemplateSpec:
    return TemplateSpec(
        key=f"torch.nn.{class_name}",
        profile="module",
        name=class_name.lower(),
        category=category,
        default_attrs={"class_name": class_name, "class_module": "torch.nn"},
        default_ports=_tensor_ports(*input_names),
    )


def _torch_op_template(class_name: str, *input_names: str) -> TemplateSpec:
    return TemplateSpec(
        key=f"torch.{class_name}",
        profile="module",
        name=class_name.lower(),
        category="张量运算",
        default_attrs={"class_name": class_name, "class_module": "torch"},
        default_ports=_tensor_ports(*input_names),
    )


_TORCH_NN_TEMPLATES = (
    _torch_nn_template("卷积", "Conv1d"),
    _torch_nn_template("卷积", "Conv2d"),
    _torch_nn_template("卷积", "Conv3d"),
    _torch_nn_template("卷积", "ConvTranspose2d"),
    _torch_nn_template("线性", "Linear"),
    _torch_nn_template("线性", "Bilinear", ("input1", "input2")),
    _torch_nn_template("线性", "Embedding", ("indices",)),
    _torch_nn_template("归一化", "BatchNorm1d"),
    _torch_nn_template("归一化", "BatchNorm2d"),
    _torch_nn_template("归一化", "LayerNorm"),
    _torch_nn_template("归一化", "GroupNorm"),
    _torch_nn_template("归一化", "RMSNorm"),
    _torch_nn_template("激活", "ReLU"),
    _torch_nn_template("激活", "GELU"),
    _torch_nn_template("激活", "SiLU"),
    _torch_nn_template("激活", "LeakyReLU"),
    _torch_nn_template("激活", "Sigmoid"),
    _torch_nn_template("激活", "Tanh"),
    _torch_nn_template("激活", "Softmax"),
    _torch_nn_template("池化", "MaxPool2d"),
    _torch_nn_template("池化", "AvgPool2d"),
    _torch_nn_template("池化", "AdaptiveAvgPool2d"),
    _torch_nn_template("正则", "Dropout"),
    _torch_nn_template("正则", "Dropout2d"),
    _torch_nn_template("注意力", "MultiheadAttention", ("query", "key", "value")),
    _torch_nn_template("注意力", "TransformerEncoderLayer"),
    _torch_nn_template("注意力", "TransformerDecoderLayer", ("tgt", "memory")),
    _torch_nn_template("循环", "RNN"),
    _torch_nn_template("循环", "LSTM"),
    _torch_nn_template("循环", "GRU"),
    _torch_nn_template("损失", "CrossEntropyLoss", ("input", "target")),
    _torch_nn_template("损失", "MSELoss", ("input", "target")),
    _torch_nn_template("损失", "BCEWithLogitsLoss", ("input", "target")),
    _torch_nn_template("损失", "L1Loss", ("input", "target")),
    _torch_nn_template("形状", "Flatten"),
    _torch_nn_template("形状", "Unflatten"),
)

_TORCH_OP_TEMPLATES = tuple(
    _torch_op_template(name, *inputs)
    for name, inputs in (
        ("reshape", ("input",)),
        ("permute", ("input",)),
        ("cat", ("a", "b")),
        ("stack", ("a", "b")),
        ("add", ("a", "b")),
        ("mul", ("a", "b")),
        ("matmul", ("a", "b")),
        ("mean", ("input",)),
        ("sum", ("input",)),
    )
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
    executors=(
        ActionExecutorSpec(key="graph.create_node", family="GraphCommand"),
        ActionExecutorSpec(key="graph.rename_node", family="GraphCommand"),
        ActionExecutorSpec(key="graph.delete_node", family="GraphCommand"),
    ),
    actions=(
        ActionSpec(
            key="node.create",
            label="添加节点",
            target=RefSetPredicate(
                min_count=0,
                max_count=1,
                entity_kinds=frozenset({"node"}),
                capabilities=frozenset({"container"}),
            ),
            executor="graph.create_node",
            executor_family="GraphCommand",
            input_schema={
                "type": "object",
                "required": ["type", "name"],
                "properties": {
                    "type": {"type": "string", "minLength": 1},
                    "name": {"type": "string", "minLength": 1},
                    "parent": {"type": ["string", "null"]},
                    "attrs": {"type": "object"},
                    "ports": {"type": "array"},
                },
                "additionalProperties": False,
            },
        ),
        ActionSpec(
            key="node.rename",
            label="重命名",
            target=RefSetPredicate(
                entity_kinds=frozenset({"node"}),
                capabilities=frozenset({"renamable"}),
            ),
            executor="graph.rename_node",
            executor_family="GraphCommand",
            input_schema={
                "type": "object",
                "required": ["new_name"],
                "properties": {"new_name": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        ),
        ActionSpec(
            key="node.delete",
            label="删除",
            target=RefSetPredicate(
                entity_kinds=frozenset({"node"}),
                capabilities=frozenset({"deletable"}),
            ),
            executor="graph.delete_node",
            executor_family="GraphCommand",
        ),
    ),
)

FILESYSTEM_PACKAGE = RegistryPackage(
    name="filesystem",
    node_profiles=tuple(_node_profile(key) for key in ("directory", "file")),
    presentations=tuple(_PRESENTATIONS[key] for key in ("directory", "file")),
    templates=(
        TemplateSpec(
            key="filesystem.directory",
            profile="directory",
            name="dir",
            category="通用",
        ),
    ),
)

ML_TORCH_PACKAGE = RegistryPackage(
    name="ml-torch",
    node_profiles=tuple(_node_profile(key) for key in ("model", "module")),
    presentations=tuple(_PRESENTATIONS[key] for key in ("model", "module")),
    port_types=frozenset({"tensor", "scalar"}),
    templates=(
        *_TORCH_NN_TEMPLATES,
        *_TORCH_OP_TEMPLATES,
        TemplateSpec(
            key="module.blank",
            profile="module",
            name="node",
            category="通用",
            default_ports=_tensor_ports("input"),
        ),
        TemplateSpec(
            key="module.container",
            profile="module",
            name="container",
            category="通用",
        ),
        TemplateSpec(
            key="model.container",
            profile="model",
            name="model",
            category="通用",
        ),
    ),
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
    presentations=tuple(
        _PRESENTATIONS[key]
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
    presentations=(_PRESENTATIONS["run"],),
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
        executors=tuple(item for package in packages for item in package.executors),
        actions=tuple(item for package in packages for item in package.actions),
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
