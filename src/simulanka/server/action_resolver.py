"""Server-authoritative action discovery and revalidation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from simulanka.registry import (
    ActionReasonCode,
    ActionSpec,
    Affordance,
    ExecutorFamily,
    Registry,
)
from simulanka.registry.profiles import EntityKind, RefSetPredicate


@dataclass(frozen=True)
class ActionTarget:
    """Policy-relevant immutable view of one selected graph reference."""

    kind: EntityKind
    id: str
    profile: str
    capabilities: frozenset[str]
    unknown_profile: bool = False
    source: str = "graph"
    writable: bool = True
    locked: bool = False
    lock_reason: str = "实体当前已锁定"

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))

    @classmethod
    def from_profile(
        cls,
        registry: Registry,
        *,
        kind: EntityKind,
        id: str,
        profile: str,
        source: str = "graph",
        writable: bool = True,
        locked: bool = False,
        lock_reason: str = "实体当前已锁定",
    ) -> ActionTarget:
        if kind == "node":
            resolved = registry.node(profile)
            capabilities = resolved.capabilities if resolved is not None else frozenset()
            canonical = resolved.key if resolved is not None else profile
            unknown = resolved is None
        elif kind == "edge":
            resolved = registry.edge(profile)
            capabilities = resolved.capabilities if resolved is not None else frozenset()
            canonical = resolved.key if resolved is not None else profile
            unknown = resolved is None
        else:
            canonical = registry.resolve_port_key(profile) or profile
            capabilities = frozenset()
            unknown = registry.resolve_port_key(profile) is None
        return cls(
            kind=kind,
            id=id,
            profile=canonical,
            capabilities=capabilities,
            unknown_profile=unknown,
            source=source,
            writable=writable,
            locked=locked,
            lock_reason=lock_reason,
        )


@dataclass(frozen=True)
class _Rejection:
    code: ActionReasonCode
    reason: str


class ActionResolver:
    """Resolve Registry actions without granting capability-derived permission."""

    def __init__(
        self,
        registry: Registry,
        *,
        supported_executors: Mapping[str, ExecutorFamily],
        allowed_actors: frozenset[str] = frozenset({"user"}),
    ) -> None:
        self._registry = registry
        self._supported_executors = MappingProxyType(dict(supported_executors))
        self._allowed_actors = frozenset(allowed_actors)

    def resolve(
        self,
        refs: Sequence[ActionTarget],
        *,
        actor: str,
    ) -> tuple[Affordance, ...]:
        """Return actions structurally relevant to the current RefSet."""
        resolved: list[Affordance] = []
        for action in sorted(self._registry.actions.values(), key=lambda item: item.key):
            target_rejection = _target_rejection(action.target, refs)
            if target_rejection is not None:
                continue
            resolved.append(self._resolve_candidate(action, refs, actor=actor))
        return tuple(resolved)

    def resolve_action(
        self,
        action_id: str,
        refs: Sequence[ActionTarget],
        *,
        actor: str,
    ) -> Affordance:
        """Revalidate one requested action, including structural mismatches."""
        action = self._registry.actions[action_id]
        rejection = _target_rejection(action.target, refs)
        if rejection is not None:
            return _affordance(action, rejection)
        return self._resolve_candidate(action, refs, actor=actor)

    def _resolve_candidate(
        self,
        action: ActionSpec,
        refs: Sequence[ActionTarget],
        *,
        actor: str,
    ) -> Affordance:
        if actor not in self._allowed_actors:
            return _affordance(
                action,
                _Rejection(
                    "actor_forbidden",
                    f"actor {actor!r} 无权执行此动作",
                ),
            )

        read_only = next((ref for ref in refs if not ref.writable), None)
        if read_only is not None:
            return _affordance(
                action,
                _Rejection(
                    "source_read_only",
                    f"来源 {read_only.source!r} 的实体 {read_only.id!r} 为只读",
                ),
            )

        locked = next((ref for ref in refs if ref.locked), None)
        if locked is not None:
            return _affordance(
                action,
                _Rejection("state_locked", locked.lock_reason),
            )

        family = self._supported_executors.get(action.executor)
        if family != action.executor_family:
            return _affordance(
                action,
                _Rejection(
                    "executor_unavailable",
                    f"执行器 {action.executor!r} 当前不可用",
                ),
            )

        return Affordance(
            id=action.key,
            label=action.label,
            enabled=True,
            reason="当前可用",
            reason_code="available",
            input_schema=action.input_schema,
        )


def _target_rejection(
    predicate: RefSetPredicate,
    refs: Sequence[ActionTarget],
) -> _Rejection | None:
    count = len(refs)
    if count < predicate.min_count or (
        predicate.max_count is not None and count > predicate.max_count
    ):
        max_label = "n" if predicate.max_count is None else str(predicate.max_count)
        return _Rejection(
            "target_count_mismatch",
            f"动作要求 {predicate.min_count}..{max_label} 个目标，当前为 {count}",
        )

    checks = [_check_target(predicate, ref) for ref in refs]
    if predicate.target_match == "all":
        return next((rejection for rejection in checks if rejection is not None), None)
    if any(rejection is None for rejection in checks):
        return None
    return checks[0] if checks else None


def _check_target(
    predicate: RefSetPredicate,
    ref: ActionTarget,
) -> _Rejection | None:
    if ref.kind not in predicate.entity_kinds:
        return _Rejection(
            "target_kind_mismatch",
            f"实体 {ref.id!r} 的种类 {ref.kind!r} 不适用于此动作",
        )
    if ref.unknown_profile:
        return _Rejection(
            "unknown_profile",
            f"实体 {ref.id!r} 使用未知 Profile {ref.profile!r}",
        )
    missing = predicate.capabilities - ref.capabilities
    if missing:
        return _Rejection(
            "missing_capability",
            f"Profile {ref.profile!r} 缺少 capability: {', '.join(sorted(missing))}",
        )
    return None


def _affordance(action: ActionSpec, rejection: _Rejection) -> Affordance:
    return Affordance(
        id=action.key,
        label=action.label,
        enabled=False,
        reason=rejection.reason,
        reason_code=rejection.code,
        input_schema=action.input_schema,
    )
