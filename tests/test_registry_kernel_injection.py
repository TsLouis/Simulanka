from __future__ import annotations

from pathlib import Path

from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp
from simulanka.layout.project import init_project
from simulanka.registry import BUILTIN_PACKAGE, SOFTWARE_SERVICE_PACKAGE, Registry
from simulanka.storage.entity_store import iter_edges, iter_nodes, load_node, save_node


def test_software_package_uses_generic_kernel_and_doctor_paths(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    registry = Registry.build(
        version=2,
        packages=(BUILTIN_PACKAGE, SOFTWARE_SERVICE_PACKAGE),
    )

    root = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="directory", name="software")],
        actor="user",
        registry=registry,
    ).nodes[0]
    api = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(
                type="software.service",
                name="api",
                parent=root,
                attrs={"runtime": "python", "team": "platform"},
            )
        ],
        actor="user",
        registry=registry,
    ).nodes[0]
    database = apply_patch_now(
        layout,
        ops=[
            CreateNodeOp(
                type="software.service",
                name="database",
                parent=root,
                attrs={"runtime": "postgres"},
            )
        ],
        actor="user",
        registry=registry,
    ).nodes[0]
    dependency = apply_patch_now(
        layout,
        ops=[
            CreateEdgeOp(
                type="software.depends_on",
                source=api,
                target=database,
            )
        ],
        actor="user",
        registry=registry,
    ).edges[0]

    nodes = {node.id: node for node in iter_nodes(layout)}
    edges = {edge.id: edge for edge in iter_edges(layout)}
    assert nodes[api].type == "software.service"
    assert nodes[api].attrs["team"] == "platform"
    assert edges[dependency].type == "software.depends_on"
    assert run_doctor(layout, registry=registry).ok

    default_report = run_doctor(layout)
    assert {issue.code for issue in default_report.issues} >= {
        "unknown_node_type",
        "unknown_edge_type",
    }
    assert {node.id for node in iter_nodes(layout)} == set(nodes)


def test_doctor_uses_the_same_profile_parent_rule(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    registry = Registry.build(
        version=2,
        packages=(BUILTIN_PACKAGE, SOFTWARE_SERVICE_PACKAGE),
    )
    root = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="directory", name="software")],
        actor="user",
        registry=registry,
    ).nodes[0]
    api = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="software.service", name="api", parent=root)],
        actor="user",
        registry=registry,
    ).nodes[0]
    database = apply_patch_now(
        layout,
        ops=[CreateNodeOp(type="software.service", name="database", parent=root)],
        actor="user",
        registry=registry,
    ).nodes[0]

    save_node(layout, load_node(layout, api).model_copy(update={"parent_id": database}))

    report = run_doctor(layout, registry=registry)
    assert "node_parent_type_mismatch" in {issue.code for issue in report.issues}
