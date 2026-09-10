from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Literal, TypeAlias

from simulanka.registry.types import ANY, PortDirection

CapabilityConsumer = Literal["validation", "action", "context", "presentation"]
ProfileKind = Literal["node", "edge", "port"]
EntityKind = Literal["node", "edge", "port"]
ValidationKind = Literal["create", "update", "doctor"]
ExecutorFamily = Literal["GraphCommand", "SessionCommand", "ProjectionCommand"]
TargetMatch = Literal["all", "any"]
ActionReasonCode = Literal[
    "available",
    "target_count_mismatch",
    "target_kind_mismatch",
    "unknown_profile",
    "missing_capability",
    "actor_forbidden",
    "source_read_only",
    "state_locked",
    "executor_unavailable",
]

_CAPABILITY_CONSUMERS = frozenset({"validation", "action", "context", "presentation"})


class RegistryBuildError(ValueError):
    """Raised when trusted packages cannot form one coherent registry."""


def _require_key(kind: str, key: str) -> None:
    if not key or key.strip() != key:
        raise RegistryBuildError(f"{kind} key must be a non-empty trimmed string: {key!r}")


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_value(item) for item in value)
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, set | frozenset):
        items = [_json_value(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value


@dataclass(frozen=True)
class ProfileEntityView:
    kind: EntityKind
    id: str
    profile: str
    attrs: Mapping[str, Any] = field(default_factory=dict)
    name: str | None = None
    parent_id: str | None = None
    node_id: str | None = None
    source_id: str | None = None
    target_id: str | None = None
    source_port_id: str | None = None
    target_port_id: str | None = None
    direction: PortDirection | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attrs", _freeze_mapping(self.attrs))


@dataclass(frozen=True)
class ProfileValidationView:
    nodes: Mapping[str, ProfileEntityView] = field(default_factory=dict)
    edges: Mapping[str, ProfileEntityView] = field(default_factory=dict)
    ports: Mapping[str, ProfileEntityView] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", MappingProxyType(dict(self.nodes)))
        object.__setattr__(self, "edges", MappingProxyType(dict(self.edges)))
        object.__setattr__(self, "ports", MappingProxyType(dict(self.ports)))


@dataclass(frozen=True)
class ProfileValidationOp:
    kind: ValidationKind
    entity: ProfileEntityView


ProfileValidator: TypeAlias = Callable[
    [ProfileValidationView, ProfileValidationOp], Sequence[str]
]


@dataclass(frozen=True)
class CapabilitySpec:
    key: str
    consumers: frozenset[CapabilityConsumer]
    description: str = ""

    def __post_init__(self) -> None:
        _require_key("capability", self.key)
        object.__setattr__(self, "consumers", frozenset(self.consumers))
        unknown = set(self.consumers) - _CAPABILITY_CONSUMERS
        if unknown:
            raise RegistryBuildError(
                f"Capability {self.key!r} has unknown consumers: {sorted(unknown)}"
            )
        if not self.consumers:
            raise RegistryBuildError(
                f"Capability {self.key!r} must have a validation, action, context, "
                "or presentation consumer"
            )


@dataclass(frozen=True)
class NodeProfileSpec:
    key: str
    extends: str | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)
    allow_parents: frozenset[str | None] | None = None
    attrs_fields: Mapping[str, str] = field(default_factory=dict)
    closed_attrs: bool | None = None
    validator: str | None = None
    presentation: str | None = None
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        _require_key("node profile", self.key)
        if self.extends is not None:
            _require_key("node base profile", self.extends)
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        if self.allow_parents is not None:
            object.__setattr__(self, "allow_parents", frozenset(self.allow_parents))
        object.__setattr__(self, "attrs_fields", _freeze_mapping(self.attrs_fields))
        object.__setattr__(self, "tags", frozenset(self.tags))


@dataclass(frozen=True)
class EdgeProfileSpec:
    key: str
    extends: str | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)
    needs_ports: bool | None = None
    source_profiles: frozenset[str] | None = None
    target_profiles: frozenset[str] | None = None
    source_capabilities: frozenset[str] = field(default_factory=frozenset)
    target_capabilities: frozenset[str] = field(default_factory=frozenset)
    source_port_direction: PortDirection | None = None
    target_port_direction: PortDirection | None = None
    validator: str | None = None
    presentation: str | None = None
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        _require_key("edge profile", self.key)
        if self.extends is not None:
            _require_key("edge base profile", self.extends)
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        if self.source_profiles is not None:
            object.__setattr__(self, "source_profiles", frozenset(self.source_profiles))
        if self.target_profiles is not None:
            object.__setattr__(self, "target_profiles", frozenset(self.target_profiles))
        object.__setattr__(self, "source_capabilities", frozenset(self.source_capabilities))
        object.__setattr__(self, "target_capabilities", frozenset(self.target_capabilities))
        object.__setattr__(self, "tags", frozenset(self.tags))


@dataclass(frozen=True)
class ResolvedProfile:
    kind: Literal["node", "edge"]
    key: str
    lineage: tuple[str, ...]
    capabilities: frozenset[str]
    validator_chain: tuple[str, ...] = ()
    presentation: str | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    allow_parents: frozenset[str | None] = field(default_factory=frozenset)
    attrs_fields: Mapping[str, str] = field(default_factory=dict)
    closed_attrs: bool = False
    needs_ports: bool = False
    source_profiles: frozenset[str] = field(default_factory=lambda: frozenset({ANY}))
    target_profiles: frozenset[str] = field(default_factory=lambda: frozenset({ANY}))
    source_capabilities: frozenset[str] = field(default_factory=frozenset)
    target_capabilities: frozenset[str] = field(default_factory=frozenset)
    source_port_direction: PortDirection | None = None
    target_port_direction: PortDirection | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "validator_chain", tuple(self.validator_chain))
        object.__setattr__(self, "tags", frozenset(self.tags))
        object.__setattr__(self, "allow_parents", frozenset(self.allow_parents))
        object.__setattr__(self, "attrs_fields", _freeze_mapping(self.attrs_fields))
        object.__setattr__(self, "source_profiles", frozenset(self.source_profiles))
        object.__setattr__(self, "target_profiles", frozenset(self.target_profiles))
        object.__setattr__(self, "source_capabilities", frozenset(self.source_capabilities))
        object.__setattr__(self, "target_capabilities", frozenset(self.target_capabilities))

    def accepts_parent(self, parent_type: str | None) -> bool:
        if self.kind != "node":
            return False
        if parent_type is None:
            return None in self.allow_parents
        return ANY in self.allow_parents or parent_type in self.allow_parents

    def accepts_source(self, profile: ResolvedProfile) -> bool:
        return self._accepts_endpoint(
            profile, self.source_profiles, self.source_capabilities
        )

    def accepts_target(self, profile: ResolvedProfile) -> bool:
        return self._accepts_endpoint(
            profile, self.target_profiles, self.target_capabilities
        )

    @staticmethod
    def _accepts_endpoint(
        profile: ResolvedProfile,
        allowed_profiles: frozenset[str],
        required_capabilities: frozenset[str],
    ) -> bool:
        profile_allowed = ANY in allowed_profiles or profile.key in allowed_profiles
        return profile_allowed and required_capabilities <= profile.capabilities


@dataclass(frozen=True)
class RefSetPredicate:
    """Structural action target selection, independent from write policy."""

    min_count: int = 1
    max_count: int | None = 1
    entity_kinds: frozenset[EntityKind] = field(
        default_factory=lambda: frozenset({"node", "edge", "port"})
    )
    capabilities: frozenset[str] = field(default_factory=frozenset)
    target_match: TargetMatch = "all"

    def __post_init__(self) -> None:
        if self.min_count < 0:
            raise RegistryBuildError("Action target min_count must be non-negative")
        if self.max_count is not None and self.max_count < self.min_count:
            raise RegistryBuildError(
                "Action target max_count must be greater than or equal to min_count"
            )
        if not self.entity_kinds:
            raise RegistryBuildError("Action target must accept at least one entity kind")
        unknown_kinds = set(self.entity_kinds) - {"node", "edge", "port"}
        if unknown_kinds:
            raise RegistryBuildError(
                f"Action target has unknown entity kinds: {sorted(unknown_kinds)}"
            )
        if self.target_match not in {"all", "any"}:
            raise RegistryBuildError(
                f"Action target match must be 'all' or 'any': {self.target_match!r}"
            )
        object.__setattr__(self, "entity_kinds", frozenset(self.entity_kinds))
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        for capability in self.capabilities:
            _require_key("action target capability", capability)


@dataclass(frozen=True)
class ActionExecutorSpec:
    key: str
    family: ExecutorFamily

    def __post_init__(self) -> None:
        _require_key("action executor", self.key)
        if self.family not in {"GraphCommand", "SessionCommand", "ProjectionCommand"}:
            raise RegistryBuildError(
                f"Action executor {self.key!r} has unknown family {self.family!r}"
            )


@dataclass(frozen=True)
class ActionSpec:
    key: str
    label: str
    target: RefSetPredicate
    executor: str
    executor_family: ExecutorFamily
    input_schema: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_key("action", self.key)
        _require_key("action label", self.label)
        _require_key("action executor", self.executor)
        if self.executor_family not in {
            "GraphCommand",
            "SessionCommand",
            "ProjectionCommand",
        }:
            raise RegistryBuildError(
                f"Action {self.key!r} has unknown executor family {self.executor_family!r}"
            )
        object.__setattr__(self, "input_schema", _freeze_mapping(self.input_schema))


@dataclass(frozen=True)
class Affordance:
    id: str
    label: str
    enabled: bool
    reason: str
    reason_code: ActionReasonCode
    input_schema: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_key("affordance id", self.id)
        _require_key("affordance label", self.label)
        if not self.reason:
            raise RegistryBuildError("Affordance reason must be non-empty")
        object.__setattr__(self, "input_schema", _freeze_mapping(self.input_schema))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "enabled": self.enabled,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "input_schema": _json_value(self.input_schema),
        }


@dataclass(frozen=True)
class PresentationSpec:
    key: str
    category: str
    palette_token: str = "default"
    icon: str = "node"
    card_fields: tuple[str, ...] = ()
    inspector_fields: tuple[str, ...] = ()
    badges: tuple[str, ...] = ()
    formatters: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_key("presentation", self.key)
        object.__setattr__(self, "card_fields", tuple(self.card_fields))
        object.__setattr__(self, "inspector_fields", tuple(self.inspector_fields))
        object.__setattr__(self, "badges", tuple(self.badges))
        object.__setattr__(self, "formatters", _freeze_mapping(self.formatters))


@dataclass(frozen=True)
class TemplatePortSpec:
    name: str
    direction: PortDirection
    port_type: str = "any"

    def __post_init__(self) -> None:
        _require_key("template port", self.name)


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    profile: str
    name: str
    category: str
    default_attrs: Mapping[str, Any] = field(default_factory=dict)
    default_ports: tuple[TemplatePortSpec, ...] = ()

    def __post_init__(self) -> None:
        _require_key("template", self.key)
        _require_key("template profile", self.profile)
        object.__setattr__(self, "default_attrs", _freeze_mapping(self.default_attrs))
        object.__setattr__(self, "default_ports", tuple(self.default_ports))


@dataclass(frozen=True)
class AliasSpec:
    kind: ProfileKind
    alias: str
    target: str

    def __post_init__(self) -> None:
        _require_key(f"{self.kind} alias", self.alias)
        _require_key(f"{self.kind} alias target", self.target)


@dataclass(frozen=True)
class RegistryPackage:
    name: str
    capabilities: tuple[CapabilitySpec, ...] = ()
    node_profiles: tuple[NodeProfileSpec, ...] = ()
    edge_profiles: tuple[EdgeProfileSpec, ...] = ()
    port_types: frozenset[str] = field(default_factory=frozenset)
    presentations: tuple[PresentationSpec, ...] = ()
    templates: tuple[TemplateSpec, ...] = ()
    executors: tuple[ActionExecutorSpec, ...] = ()
    actions: tuple[ActionSpec, ...] = ()
    aliases: tuple[AliasSpec, ...] = ()
    validators: Mapping[str, ProfileValidator] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_key("package", self.name)
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "node_profiles", tuple(self.node_profiles))
        object.__setattr__(self, "edge_profiles", tuple(self.edge_profiles))
        object.__setattr__(self, "port_types", frozenset(self.port_types))
        object.__setattr__(self, "presentations", tuple(self.presentations))
        object.__setattr__(self, "templates", tuple(self.templates))
        object.__setattr__(self, "executors", tuple(self.executors))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "validators", MappingProxyType(dict(self.validators)))


@dataclass(frozen=True)
class Registry:
    version: int
    packages: tuple[str, ...]
    capabilities: Mapping[str, CapabilitySpec]
    node_profiles: Mapping[str, ResolvedProfile]
    edge_profiles: Mapping[str, ResolvedProfile]
    port_types: frozenset[str]
    presentations: Mapping[str, PresentationSpec]
    templates: Mapping[str, TemplateSpec]
    executors: Mapping[str, ActionExecutorSpec]
    actions: Mapping[str, ActionSpec]
    validators: Mapping[str, ProfileValidator]
    node_aliases: Mapping[str, str]
    edge_aliases: Mapping[str, str]
    port_aliases: Mapping[str, str]
    descriptor_digest: str

    @classmethod
    def build(cls, *, version: int, packages: Iterable[RegistryPackage]) -> Registry:
        if version < 1:
            raise RegistryBuildError("Registry version must be positive")

        package_list = tuple(packages)
        package_names: set[str] = set()
        capabilities: dict[str, CapabilitySpec] = {}
        capability_sources: dict[str, str] = {}
        node_specs: dict[str, NodeProfileSpec] = {}
        node_sources: dict[str, str] = {}
        edge_specs: dict[str, EdgeProfileSpec] = {}
        edge_sources: dict[str, str] = {}
        port_types: set[str] = set()
        port_sources: dict[str, str] = {}
        presentations: dict[str, PresentationSpec] = {}
        presentation_sources: dict[str, str] = {}
        templates: dict[str, TemplateSpec] = {}
        template_sources: dict[str, str] = {}
        executors: dict[str, ActionExecutorSpec] = {}
        executor_sources: dict[str, str] = {}
        actions: dict[str, ActionSpec] = {}
        action_sources: dict[str, str] = {}
        validators: dict[str, ProfileValidator] = {}
        validator_sources: dict[str, str] = {}
        aliases: list[tuple[AliasSpec, str]] = []

        for package in package_list:
            if package.name in package_names:
                raise RegistryBuildError(f"Duplicate package name {package.name!r}")
            package_names.add(package.name)
            cls._add_unique(
                capabilities,
                capability_sources,
                package.capabilities,
                package.name,
                "capability",
            )
            cls._add_unique(
                node_specs,
                node_sources,
                package.node_profiles,
                package.name,
                "node profile",
            )
            cls._add_unique(
                edge_specs,
                edge_sources,
                package.edge_profiles,
                package.name,
                "edge profile",
            )
            cls._add_unique(
                presentations,
                presentation_sources,
                package.presentations,
                package.name,
                "presentation",
            )
            cls._add_unique(
                templates,
                template_sources,
                package.templates,
                package.name,
                "template",
            )
            cls._add_unique(
                executors,
                executor_sources,
                package.executors,
                package.name,
                "action executor",
            )
            cls._add_unique(
                actions,
                action_sources,
                package.actions,
                package.name,
                "action",
            )
            for port_type in package.port_types:
                _require_key("port type", port_type)
                if port_type in port_types:
                    raise RegistryBuildError(
                        f"Duplicate port type {port_type!r} from packages "
                        f"{port_sources[port_type]!r} and {package.name!r}"
                    )
                port_types.add(port_type)
                port_sources[port_type] = package.name
            for validator_key, validator in package.validators.items():
                _require_key("validator", validator_key)
                if validator_key in validators:
                    raise RegistryBuildError(
                        f"Duplicate validator {validator_key!r} from packages "
                        f"{validator_sources[validator_key]!r} and {package.name!r}"
                    )
                validators[validator_key] = validator
                validator_sources[validator_key] = package.name
            aliases.extend((alias, package.name) for alias in package.aliases)

        node_aliases = cls._resolve_aliases("node", aliases, set(node_specs))
        edge_aliases = cls._resolve_aliases("edge", aliases, set(edge_specs))
        port_aliases = cls._resolve_aliases("port", aliases, port_types)
        resolved_nodes = cls._resolve_nodes(
            node_specs, node_aliases, capabilities, presentations, validators
        )
        resolved_edges = cls._resolve_edges(
            edge_specs,
            edge_aliases,
            resolved_nodes,
            node_aliases,
            capabilities,
            presentations,
            validators,
        )
        templates = cls._resolve_templates(
            templates, resolved_nodes, node_aliases, port_types, port_aliases
        )
        cls._validate_actions(actions, executors, capabilities)

        frozen_capabilities = MappingProxyType(dict(capabilities))
        frozen_nodes = MappingProxyType(resolved_nodes)
        frozen_edges = MappingProxyType(resolved_edges)
        frozen_presentations = MappingProxyType(dict(presentations))
        frozen_templates = MappingProxyType(dict(templates))
        frozen_executors = MappingProxyType(dict(executors))
        frozen_actions = MappingProxyType(dict(actions))
        frozen_validators = MappingProxyType(dict(validators))
        frozen_node_aliases = MappingProxyType(node_aliases)
        frozen_edge_aliases = MappingProxyType(edge_aliases)
        frozen_port_aliases = MappingProxyType(port_aliases)
        frozen_ports = frozenset(port_types)
        names = tuple(package.name for package in package_list)

        payload = cls._descriptor_payload(
            version=version,
            packages=names,
            capabilities=frozen_capabilities,
            node_profiles=frozen_nodes,
            edge_profiles=frozen_edges,
            port_types=frozen_ports,
            presentations=frozen_presentations,
            templates=frozen_templates,
            actions=frozen_actions,
            node_aliases=frozen_node_aliases,
            edge_aliases=frozen_edge_aliases,
            port_aliases=frozen_port_aliases,
        )
        try:
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except TypeError as exc:
            raise RegistryBuildError(f"Registry descriptor contains non-JSON data: {exc}") from exc
        digest = sha256(canonical.encode("utf-8")).hexdigest()

        return cls(
            version=version,
            packages=names,
            capabilities=frozen_capabilities,
            node_profiles=frozen_nodes,
            edge_profiles=frozen_edges,
            port_types=frozen_ports,
            presentations=frozen_presentations,
            templates=frozen_templates,
            executors=frozen_executors,
            actions=frozen_actions,
            validators=frozen_validators,
            node_aliases=frozen_node_aliases,
            edge_aliases=frozen_edge_aliases,
            port_aliases=frozen_port_aliases,
            descriptor_digest=digest,
        )

    @staticmethod
    def _add_unique(
        target: dict[str, Any],
        sources: dict[str, str],
        values: Iterable[Any],
        package: str,
        kind: str,
    ) -> None:
        for value in values:
            key = value.key
            if key in target:
                raise RegistryBuildError(
                    f"Duplicate {kind} {key!r} from packages "
                    f"{sources[key]!r} and {package!r}"
                )
            target[key] = value
            sources[key] = package

    @staticmethod
    def _resolve_aliases(
        kind: ProfileKind,
        aliases: Iterable[tuple[AliasSpec, str]],
        canonical_keys: set[str],
    ) -> dict[str, str]:
        raw: dict[str, str] = {}
        sources: dict[str, str] = {}
        for alias_spec, package in aliases:
            if alias_spec.kind != kind:
                continue
            if alias_spec.alias in canonical_keys:
                raise RegistryBuildError(
                    f"{kind} alias {alias_spec.alias!r} collides with a canonical key"
                )
            if alias_spec.alias in raw:
                raise RegistryBuildError(
                    f"Duplicate {kind} alias {alias_spec.alias!r} from packages "
                    f"{sources[alias_spec.alias]!r} and {package!r}"
                )
            raw[alias_spec.alias] = alias_spec.target
            sources[alias_spec.alias] = package

        resolved: dict[str, str] = {}

        def visit(alias: str, chain: tuple[str, ...]) -> str:
            if alias in resolved:
                return resolved[alias]
            if alias in chain:
                cycle = " -> ".join((*chain, alias))
                raise RegistryBuildError(f"{kind} alias cycle: {cycle}")
            target = raw[alias]
            if target in canonical_keys:
                canonical = target
            elif target in raw:
                canonical = visit(target, (*chain, alias))
            else:
                raise RegistryBuildError(
                    f"Unknown {kind} alias target {target!r} for {alias!r}"
                )
            resolved[alias] = canonical
            return canonical

        for alias_key in sorted(raw):
            visit(alias_key, ())
        return resolved

    @classmethod
    def _resolve_nodes(
        cls,
        specs: Mapping[str, NodeProfileSpec],
        aliases: Mapping[str, str],
        capabilities: Mapping[str, CapabilitySpec],
        presentations: Mapping[str, PresentationSpec],
        validators: Mapping[str, ProfileValidator],
    ) -> dict[str, ResolvedProfile]:
        resolved: dict[str, ResolvedProfile] = {}
        visiting: list[str] = []

        def canonical(key: str) -> str:
            return aliases.get(key, key)

        def visit(key: str) -> ResolvedProfile:
            if key in resolved:
                return resolved[key]
            if key in visiting:
                start = visiting.index(key)
                cycle = " -> ".join((*visiting[start:], key))
                raise RegistryBuildError(f"Node profile inheritance cycle: {cycle}")
            visiting.append(key)
            spec = specs[key]
            base: ResolvedProfile | None = None
            if spec.extends is not None:
                base_key = canonical(spec.extends)
                if base_key not in specs:
                    raise RegistryBuildError(
                        f"Unknown node base {spec.extends!r} for profile {key!r}"
                    )
                base = visit(base_key)

            cls._validate_capabilities(key, spec.capabilities, capabilities)
            if spec.validator is not None and spec.validator not in validators:
                raise RegistryBuildError(
                    f"Node profile {key!r} references unknown validator {spec.validator!r}"
                )
            presentation = spec.presentation or (base.presentation if base else None)
            if presentation is not None and presentation not in presentations:
                raise RegistryBuildError(
                    f"Node profile {key!r} references unknown presentation {presentation!r}"
                )
            raw_parents = (
                spec.allow_parents
                if spec.allow_parents is not None
                else (base.allow_parents if base else frozenset())
            )
            parents = frozenset(
                parent if parent is None or parent == ANY else canonical(parent)
                for parent in raw_parents
            )
            unknown_parents = {
                parent
                for parent in parents
                if parent is not None and parent != ANY and parent not in specs
            }
            if unknown_parents:
                raise RegistryBuildError(
                    f"Node profile {key!r} has unknown parents: {sorted(unknown_parents)}"
                )
            attrs = dict(base.attrs_fields) if base else {}
            attrs.update(spec.attrs_fields)
            validators_chain = base.validator_chain if base else ()
            if spec.validator is not None:
                validators_chain = (*validators_chain, spec.validator)
            item = ResolvedProfile(
                kind="node",
                key=key,
                lineage=(*(base.lineage if base else ()), key),
                capabilities=(base.capabilities if base else frozenset()) | spec.capabilities,
                validator_chain=validators_chain,
                presentation=presentation,
                tags=(base.tags if base else frozenset()) | spec.tags,
                allow_parents=parents,
                attrs_fields=attrs,
                closed_attrs=(
                    spec.closed_attrs
                    if spec.closed_attrs is not None
                    else (base.closed_attrs if base else False)
                ),
            )
            visiting.pop()
            resolved[key] = item
            return item

        for key in sorted(specs):
            visit(key)
        return resolved

    @classmethod
    def _resolve_edges(
        cls,
        specs: Mapping[str, EdgeProfileSpec],
        aliases: Mapping[str, str],
        node_profiles: Mapping[str, ResolvedProfile],
        node_aliases: Mapping[str, str],
        capabilities: Mapping[str, CapabilitySpec],
        presentations: Mapping[str, PresentationSpec],
        validators: Mapping[str, ProfileValidator],
    ) -> dict[str, ResolvedProfile]:
        resolved: dict[str, ResolvedProfile] = {}
        visiting: list[str] = []

        def canonical_edge(key: str) -> str:
            return aliases.get(key, key)

        def canonical_node(key: str) -> str:
            return node_aliases.get(key, key)

        def visit(key: str) -> ResolvedProfile:
            if key in resolved:
                return resolved[key]
            if key in visiting:
                start = visiting.index(key)
                cycle = " -> ".join((*visiting[start:], key))
                raise RegistryBuildError(f"Edge profile inheritance cycle: {cycle}")
            visiting.append(key)
            spec = specs[key]
            base: ResolvedProfile | None = None
            if spec.extends is not None:
                base_key = canonical_edge(spec.extends)
                if base_key not in specs:
                    raise RegistryBuildError(
                        f"Unknown edge base {spec.extends!r} for profile {key!r}"
                    )
                base = visit(base_key)

            cls._validate_capabilities(key, spec.capabilities, capabilities)
            cls._validate_capabilities(key, spec.source_capabilities, capabilities)
            cls._validate_capabilities(key, spec.target_capabilities, capabilities)
            if spec.validator is not None and spec.validator not in validators:
                raise RegistryBuildError(
                    f"Edge profile {key!r} references unknown validator {spec.validator!r}"
                )
            presentation = spec.presentation or (base.presentation if base else None)
            if presentation is not None and presentation not in presentations:
                raise RegistryBuildError(
                    f"Edge profile {key!r} references unknown presentation {presentation!r}"
                )
            source_profiles = cls._endpoint_profiles(
                spec.source_profiles,
                base.source_profiles if base else frozenset({ANY}),
                canonical_node,
                node_profiles,
                key,
                "source",
            )
            target_profiles = cls._endpoint_profiles(
                spec.target_profiles,
                base.target_profiles if base else frozenset({ANY}),
                canonical_node,
                node_profiles,
                key,
                "target",
            )
            needs_ports = (
                spec.needs_ports
                if spec.needs_ports is not None
                else (base.needs_ports if base else False)
            )
            source_direction = (
                spec.source_port_direction
                if spec.source_port_direction is not None
                else (base.source_port_direction if base else None)
            )
            target_direction = (
                spec.target_port_direction
                if spec.target_port_direction is not None
                else (base.target_port_direction if base else None)
            )
            if needs_ports and (source_direction is None or target_direction is None):
                raise RegistryBuildError(
                    f"Edge profile {key!r} requires source and target port directions"
                )
            if not needs_ports and (source_direction is not None or target_direction is not None):
                raise RegistryBuildError(
                    f"Edge profile {key!r} declares port directions but needs_ports is false"
                )
            validator_chain = base.validator_chain if base else ()
            if spec.validator is not None:
                validator_chain = (*validator_chain, spec.validator)
            item = ResolvedProfile(
                kind="edge",
                key=key,
                lineage=(*(base.lineage if base else ()), key),
                capabilities=(base.capabilities if base else frozenset()) | spec.capabilities,
                validator_chain=validator_chain,
                presentation=presentation,
                tags=(base.tags if base else frozenset()) | spec.tags,
                needs_ports=needs_ports,
                source_profiles=source_profiles,
                target_profiles=target_profiles,
                source_capabilities=(
                    base.source_capabilities if base else frozenset()
                )
                | spec.source_capabilities,
                target_capabilities=(
                    base.target_capabilities if base else frozenset()
                )
                | spec.target_capabilities,
                source_port_direction=source_direction,
                target_port_direction=target_direction,
            )
            visiting.pop()
            resolved[key] = item
            return item

        for key in sorted(specs):
            visit(key)
        return resolved

    @staticmethod
    def _validate_capabilities(
        owner: str,
        referenced: frozenset[str],
        capabilities: Mapping[str, CapabilitySpec],
    ) -> None:
        unknown = referenced - capabilities.keys()
        if unknown:
            raise RegistryBuildError(
                f"Profile {owner!r} references unknown capabilities: {sorted(unknown)}"
            )

    @staticmethod
    def _validate_actions(
        actions: Mapping[str, ActionSpec],
        executors: Mapping[str, ActionExecutorSpec],
        capabilities: Mapping[str, CapabilitySpec],
    ) -> None:
        for action in actions.values():
            unknown = action.target.capabilities - capabilities.keys()
            if unknown:
                raise RegistryBuildError(
                    f"Action {action.key!r} references unknown capabilities: {sorted(unknown)}"
                )
            non_action = sorted(
                key
                for key in action.target.capabilities
                if "action" not in capabilities[key].consumers
            )
            if non_action:
                raise RegistryBuildError(
                    f"Action {action.key!r} references capabilities without an action "
                    f"consumer: {non_action}"
                )
            executor = executors.get(action.executor)
            if executor is None:
                raise RegistryBuildError(
                    f"Action {action.key!r} references unknown executor {action.executor!r}"
                )
            if executor.family != action.executor_family:
                raise RegistryBuildError(
                    f"Action {action.key!r} declares {action.executor_family} but executor "
                    f"{executor.key!r} belongs to {executor.family}"
                )

    @staticmethod
    def _endpoint_profiles(
        requested: frozenset[str] | None,
        inherited: frozenset[str],
        canonical: Callable[[str], str],
        node_profiles: Mapping[str, ResolvedProfile],
        edge_key: str,
        side: str,
    ) -> frozenset[str]:
        values = inherited if requested is None else requested
        normalized = frozenset(ANY if value == ANY else canonical(value) for value in values)
        unknown = {value for value in normalized if value != ANY and value not in node_profiles}
        if unknown:
            raise RegistryBuildError(
                f"Edge profile {edge_key!r} has unknown {side} profiles: {sorted(unknown)}"
            )
        return normalized

    @staticmethod
    def _resolve_templates(
        templates: Mapping[str, TemplateSpec],
        nodes: Mapping[str, ResolvedProfile],
        node_aliases: Mapping[str, str],
        port_types: set[str],
        port_aliases: Mapping[str, str],
    ) -> dict[str, TemplateSpec]:
        resolved: dict[str, TemplateSpec] = {}
        for template in templates.values():
            profile = node_aliases.get(template.profile, template.profile)
            if profile not in nodes:
                raise RegistryBuildError(
                    f"Template {template.key!r} references unknown profile {template.profile!r}"
                )
            ports: list[TemplatePortSpec] = []
            for port in template.default_ports:
                port_type = port_aliases.get(port.port_type, port.port_type)
                if port_type not in port_types:
                    raise RegistryBuildError(
                        f"Template {template.key!r} references unknown port type "
                        f"{port.port_type!r}"
                    )
                ports.append(replace(port, port_type=port_type))
            resolved[template.key] = replace(
                template,
                profile=profile,
                default_ports=tuple(ports),
            )
        return resolved

    def resolve_node_key(self, key: str) -> str | None:
        if key in self.node_profiles:
            return key
        return self.node_aliases.get(key)

    def resolve_edge_key(self, key: str) -> str | None:
        if key in self.edge_profiles:
            return key
        return self.edge_aliases.get(key)

    def resolve_port_key(self, key: str) -> str | None:
        if key in self.port_types:
            return key
        return self.port_aliases.get(key)

    def node(self, key: str) -> ResolvedProfile | None:
        canonical = self.resolve_node_key(key)
        return self.node_profiles.get(canonical) if canonical is not None else None

    def edge(self, key: str) -> ResolvedProfile | None:
        canonical = self.resolve_edge_key(key)
        return self.edge_profiles.get(canonical) if canonical is not None else None

    def validate_profile(
        self,
        profile: ResolvedProfile,
        view: ProfileValidationView,
        op: ProfileValidationOp,
    ) -> list[str]:
        errors: list[str] = []
        for validator_key in profile.validator_chain:
            validator = self.validators[validator_key]
            try:
                result = validator(view, op)
            except Exception as exc:  # trusted extension still fails closed
                errors.append(
                    f"Validator `{validator_key}` failed: {type(exc).__name__}: {exc}"
                )
                continue
            if isinstance(result, str):
                errors.append(
                    f"Validator `{validator_key}` returned a string instead of a sequence"
                )
                continue
            for error in result:
                if not isinstance(error, str):
                    errors.append(
                        f"Validator `{validator_key}` returned a non-string error"
                    )
                    break
                errors.append(error)
        return errors

    def descriptor(self) -> dict[str, Any]:
        payload = self._descriptor_payload(
            version=self.version,
            packages=self.packages,
            capabilities=self.capabilities,
            node_profiles=self.node_profiles,
            edge_profiles=self.edge_profiles,
            port_types=self.port_types,
            presentations=self.presentations,
            templates=self.templates,
            actions=self.actions,
            node_aliases=self.node_aliases,
            edge_aliases=self.edge_aliases,
            port_aliases=self.port_aliases,
        )
        return {**payload, "digest": self.descriptor_digest}

    @staticmethod
    def _descriptor_payload(
        *,
        version: int,
        packages: tuple[str, ...],
        capabilities: Mapping[str, CapabilitySpec],
        node_profiles: Mapping[str, ResolvedProfile],
        edge_profiles: Mapping[str, ResolvedProfile],
        port_types: frozenset[str],
        presentations: Mapping[str, PresentationSpec],
        templates: Mapping[str, TemplateSpec],
        actions: Mapping[str, ActionSpec],
        node_aliases: Mapping[str, str],
        edge_aliases: Mapping[str, str],
        port_aliases: Mapping[str, str],
    ) -> dict[str, Any]:
        return {
            "version": version,
            "packages": list(packages),
            "capabilities": [
                {
                    "key": item.key,
                    "consumers": sorted(item.consumers),
                    "description": item.description,
                }
                for item in sorted(capabilities.values(), key=lambda item: item.key)
            ],
            "node_profiles": [
                {
                    "key": item.key,
                    "lineage": list(item.lineage),
                    "capabilities": sorted(item.capabilities),
                    "allow_parents": sorted(
                        item.allow_parents,
                        key=lambda value: "" if value is None else value,
                    ),
                    "attrs_fields": dict(item.attrs_fields),
                    "closed_attrs": item.closed_attrs,
                    "validators": list(item.validator_chain),
                    "presentation": item.presentation,
                    "tags": sorted(item.tags),
                }
                for item in sorted(node_profiles.values(), key=lambda item: item.key)
            ],
            "edge_profiles": [
                {
                    "key": item.key,
                    "lineage": list(item.lineage),
                    "capabilities": sorted(item.capabilities),
                    "needs_ports": item.needs_ports,
                    "source_profiles": sorted(item.source_profiles),
                    "target_profiles": sorted(item.target_profiles),
                    "source_capabilities": sorted(item.source_capabilities),
                    "target_capabilities": sorted(item.target_capabilities),
                    "source_port_direction": item.source_port_direction,
                    "target_port_direction": item.target_port_direction,
                    "validators": list(item.validator_chain),
                    "presentation": item.presentation,
                    "tags": sorted(item.tags),
                }
                for item in sorted(edge_profiles.values(), key=lambda item: item.key)
            ],
            "port_types": sorted(port_types),
            "presentations": [
                {
                    "key": item.key,
                    "category": item.category,
                    "palette_token": item.palette_token,
                    "icon": item.icon,
                    "card_fields": list(item.card_fields),
                    "inspector_fields": list(item.inspector_fields),
                    "badges": list(item.badges),
                    "formatters": dict(sorted(item.formatters.items())),
                }
                for item in sorted(presentations.values(), key=lambda item: item.key)
            ],
            "templates": [
                {
                    "key": item.key,
                    "profile": item.profile,
                    "name": item.name,
                    "category": item.category,
                    "default_attrs": _json_value(item.default_attrs),
                    "default_ports": [
                        {
                            "name": port.name,
                            "direction": port.direction,
                            "port_type": port.port_type,
                        }
                        for port in item.default_ports
                    ],
                }
                for item in sorted(templates.values(), key=lambda item: item.key)
            ],
            "actions": [
                {
                    "id": item.key,
                    "label": item.label,
                    "target": {
                        "min_count": item.target.min_count,
                        "max_count": item.target.max_count,
                        "entity_kinds": sorted(item.target.entity_kinds),
                        "capabilities": sorted(item.target.capabilities),
                        "target_match": item.target.target_match,
                    },
                    "executor": item.executor,
                    "executor_family": item.executor_family,
                    "input_schema": _json_value(item.input_schema),
                }
                for item in sorted(actions.values(), key=lambda item: item.key)
            ],
            "aliases": {
                "node": dict(sorted(node_aliases.items())),
                "edge": dict(sorted(edge_aliases.items())),
                "port": dict(sorted(port_aliases.items())),
            },
        }
