from __future__ import annotations

import json
from pathlib import Path

from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp, CreatePortOp
from simulanka.kernel.migration import plan_migrations
from simulanka.layout.project import init_project


def _set_registry_v1(manifest_path: Path) -> None:
    payload = json.loads(manifest_path.read_text("utf-8"))
    payload["registry_version"] = 1
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_registry_v1_project_can_still_author_nodes_ports_and_edges(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _set_registry_v1(layout.manifest_path)

    directory = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="directory", name="context")],
        actor="user",
    ).nodes[0]
    nodes = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(type="claim", name="source", parent=directory),
            CreateNodeOp(type="claim", name="target", parent=directory),
        ],
        actor="user",
    )
    source, target = nodes.nodes
    ports = apply_patch_now(
        layout,
        ops=[
            CreatePortOp(
                node=source,
                name="out",
                direction="out",
                port_type="any",
            ),
            CreatePortOp(
                node=target,
                name="in",
                direction="in",
                port_type="any",
            ),
        ],
        actor="user",
    )
    edge = apply_patch_now(
        layout,
        ops=[
            CreateEdgeOp(
                type="data_flow",
                source=ports.ports[0],
                target=ports.ports[1],
            )
        ],
        actor="user",
    )

    assert edge.edges
    # Compatibility does not silently rewrite the manifest or manufacture a
    # migration event. The explicit migration path remains available.
    assert layout.load_manifest().registry_version == 1
    plan = plan_migrations(layout)
    assert [(step.kind, step.from_version, step.to_version) for step in plan.steps] == [
        ("registry", 1, 2)
    ]
