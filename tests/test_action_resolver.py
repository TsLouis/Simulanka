from __future__ import annotations

from simulanka.registry import (
    BUILTIN_PACKAGES,
    DEFAULT_REGISTRY,
    ActionExecutorSpec,
    ActionSpec,
    ExecutorFamily,
    RefSetPredicate,
    Registry,
    RegistryPackage,
)
from simulanka.server.action_resolver import ActionResolver, ActionTarget

GRAPH_EXECUTORS: dict[str, ExecutorFamily] = {
    "graph.create_node": "GraphCommand",
    "graph.rename_node": "GraphCommand",
    "graph.delete_node": "GraphCommand",
}


def _target(
    profile: str,
    *,
    writable: bool = True,
    locked: bool = False,
) -> ActionTarget:
    return ActionTarget.from_profile(
        DEFAULT_REGISTRY,
        kind="node",
        id=f"node:{profile}",
        profile=profile,
        source="projection" if not writable else "graph",
        writable=writable,
        locked=locked,
        lock_reason="用户已锁定此节点",
    )


def test_resolver_intersects_capability_actor_source_state_and_executor() -> None:
    resolver = ActionResolver(
        DEFAULT_REGISTRY,
        supported_executors=GRAPH_EXECUTORS,
    )

    model_actions = {item.id: item for item in resolver.resolve((_target("model"),), actor="user")}
    assert model_actions["node.rename"].enabled
    assert model_actions["node.delete"].enabled
    directory_actions = resolver.resolve((_target("directory"),), actor="user")
    assert len(directory_actions) == 1
    assert directory_actions[0].id == "node.create"
    assert directory_actions[0].enabled

    missing_capability = resolver.resolve_action(
        "node.delete", (_target("task"),), actor="user"
    )
    assert not missing_capability.enabled
    assert missing_capability.reason_code == "missing_capability"

    actor_denied = resolver.resolve_action(
        "node.rename", (_target("model"),), actor="agent"
    )
    assert actor_denied.reason_code == "actor_forbidden"

    projected = resolver.resolve_action(
        "node.delete", (_target("model", writable=False),), actor="user"
    )
    assert projected.reason_code == "source_read_only"
    assert "projection" in projected.reason

    locked = resolver.resolve_action(
        "node.rename", (_target("model", locked=True),), actor="user"
    )
    assert locked.reason_code == "state_locked"
    assert locked.reason == "用户已锁定此节点"

    unavailable = ActionResolver(DEFAULT_REGISTRY, supported_executors={}).resolve_action(
        "node.rename", (_target("model"),), actor="user"
    )
    assert unavailable.reason_code == "executor_unavailable"


def test_resolver_reports_unknown_profile_and_refset_shape() -> None:
    resolver = ActionResolver(
        DEFAULT_REGISTRY,
        supported_executors=GRAPH_EXECUTORS,
    )
    unknown = _target("uninstalled.domain")
    result = resolver.resolve_action("node.rename", (unknown,), actor="user")
    assert result.reason_code == "unknown_profile"

    too_many = resolver.resolve_action(
        "node.rename",
        (_target("model"), _target("module")),
        actor="user",
    )
    assert too_many.reason_code == "target_count_mismatch"

    edge = ActionTarget.from_profile(
        DEFAULT_REGISTRY,
        kind="edge",
        id="edge:1",
        profile="data_flow",
    )
    wrong_kind = resolver.resolve_action("node.rename", (edge,), actor="user")
    assert wrong_kind.reason_code == "target_kind_mismatch"


def test_resolver_supports_all_and_any_capability_matching() -> None:
    extension = RegistryPackage(
        name="context-actions",
        executors=(
            ActionExecutorSpec(key="session.attach_all", family="SessionCommand"),
            ActionExecutorSpec(key="session.attach_any", family="SessionCommand"),
        ),
        actions=(
            ActionSpec(
                key="context.attach_all",
                label="全部附加到上下文",
                target=RefSetPredicate(
                    min_count=1,
                    max_count=None,
                    entity_kinds=frozenset({"node"}),
                    capabilities=frozenset({"contextualizable"}),
                    target_match="all",
                ),
                executor="session.attach_all",
                executor_family="SessionCommand",
            ),
            ActionSpec(
                key="context.attach_any",
                label="附加可用目标",
                target=RefSetPredicate(
                    min_count=1,
                    max_count=None,
                    entity_kinds=frozenset({"node"}),
                    capabilities=frozenset({"contextualizable"}),
                    target_match="any",
                ),
                executor="session.attach_any",
                executor_family="SessionCommand",
            ),
        ),
    )
    registry = Registry.build(version=2, packages=(*BUILTIN_PACKAGES, extension))
    resolver = ActionResolver(
        registry,
        supported_executors={
            **GRAPH_EXECUTORS,
            "session.attach_all": "SessionCommand",
            "session.attach_any": "SessionCommand",
        },
    )
    known = ActionTarget.from_profile(
        registry,
        kind="node",
        id="node:model",
        profile="model",
    )
    unknown = ActionTarget.from_profile(
        registry,
        kind="node",
        id="node:unknown",
        profile="uninstalled.domain",
    )

    actions = {item.id: item for item in resolver.resolve((known, unknown), actor="user")}
    assert "context.attach_all" not in actions
    assert actions["context.attach_any"].enabled

    all_result = resolver.resolve_action(
        "context.attach_all", (known, unknown), actor="user"
    )
    assert all_result.reason_code == "unknown_profile"
