"""End-to-end test for the torch.export importer.

Skipped if ``torch`` is not installed (the importer is an optional dependency).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

torch = pytest.importorskip("torch")

from simulanka.importer import import_model  # noqa: E402
from simulanka.kernel.apply import apply_patch  # noqa: E402
from simulanka.kernel.doctor import run_doctor  # noqa: E402
from simulanka.kernel.intent import CreateNodeOp, PatchIntent  # noqa: E402
from simulanka.layout.project import ProjectLayout, init_project  # noqa: E402
from simulanka.storage.entity_store import (  # noqa: E402
    iter_edges,
    iter_nodes,
    iter_ports,
)


def _make_directory(layout: ProjectLayout, name: str) -> None:
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name=name)],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )


def _build_tiny_mlp() -> tuple[Any, tuple[Any, ...]]:
    """A 2-block MLP. Keep the class defs at module scope so torch.export can pickle types."""
    import torch.nn as nn

    class Block(nn.Module):
        def __init__(self, d: int) -> None:
            super().__init__()
            self.lin = nn.Linear(d, d)
            self.act = nn.ReLU()

        def forward(self, x: Any) -> Any:
            return self.act(self.lin(x))

    class TinyMLP(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.b1 = Block(8)
            self.b2 = Block(8)
            self.head = nn.Linear(8, 2)

        def forward(self, x: Any) -> Any:
            h = self.b1(x)
            h = self.b2(h)
            return self.head(h)

    return TinyMLP(), (torch.randn(2, 8),)


def test_imports_module_hierarchy_and_data_flow(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    # `model` nodes must live under a directory; create one first.
    _make_directory(layout, "models")
    result = import_model(layout, _build_tiny_mlp, name="TinyMLP", parent="/models")

    # All expected fqns are present in the returned map.
    expected_fqns = {"", "b1", "b1.lin", "b1.act", "b2", "b2.lin", "b2.act", "head"}
    assert set(result.module_node_ids) == expected_fqns

    # Node-type distribution: 1 model + 7 module nodes.
    types = [n.type for n in iter_nodes(layout)]
    assert types.count("model") == 1
    assert types.count("module") == 7

    # Every module/model node got an `in` and `out` port.
    ports_by_node: dict[str, set[str]] = {}
    for p in iter_ports(layout):
        ports_by_node.setdefault(p.node_id, set()).add(p.name)
    for node_id in result.module_node_ids.values():
        assert ports_by_node.get(node_id) == {"in", "out"}, (
            f"node {node_id} should have both io ports"
        )

    # Peer-level data_flow edges:
    #   b1 → b2, b2 → head (top level)
    #   within b1 and b2:  *.lin → *.act
    data_flow = [e for e in iter_edges(layout) if e.type == "data_flow"]
    by_endpoints = {(e.source_id, e.target_id) for e in data_flow}

    ids = result.module_node_ids
    expected_pairs = {
        (ids["b1"], ids["b2"]),
        (ids["b2"], ids["head"]),
        (ids["b1.lin"], ids["b1.act"]),
        (ids["b2.lin"], ids["b2.act"]),
    }
    assert expected_pairs.issubset(by_endpoints), (
        f"missing data_flow pairs. got={by_endpoints}"
    )

    # Every data_flow edge references the correct port directions (validated by
    # apply_patch, but double-check via doctor).
    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_invalid_name_rejected(tmp_path: Path) -> None:
    from simulanka.importer import ModelImportError

    layout = init_project(tmp_path, with_scaffold=False).layout
    _make_directory(layout, "models")
    with pytest.raises(ModelImportError):
        import_model(layout, _build_tiny_mlp, name="bad.name", parent="/models")


def test_diverging_ancestors_unit() -> None:
    from simulanka.importer.torch_export import _diverging_ancestors

    assert _diverging_ancestors("b1.lin", "b1.act") == ("b1.lin", "b1.act")
    assert _diverging_ancestors("b1.act", "b2.lin") == ("b1", "b2")
    assert _diverging_ancestors("b1", "b1.lin") is None
    assert _diverging_ancestors("x", "x") is None
    assert _diverging_ancestors("a.b.c", "a.b.d") == ("a.b.c", "a.b.d")
    assert _diverging_ancestors("a.b.c", "a.d") == ("a.b", "a.d")


def _build_residual_net() -> tuple[Any, tuple[Any, ...]]:
    """Toy transformer-shaped net with a functional ``+`` residual."""
    import torch.nn as nn

    class ResBlock(nn.Module):
        def __init__(self, d: int) -> None:
            super().__init__()
            self.norm = nn.LayerNorm(d)
            self.lin = nn.Linear(d, d)

        def forward(self, x: Any) -> Any:
            return x + self.lin(self.norm(x))

    class Net(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.b = ResBlock(4)
            self.head = nn.Linear(4, 2)

        def forward(self, x: Any) -> Any:
            return self.head(self.b(x))

    return Net(), (torch.randn(2, 4),)


def test_functional_residual_captured(tmp_path: Path) -> None:
    """Functional ``+`` residual still yields the ``b -> head`` edge."""
    from simulanka.storage.entity_store import iter_edges

    layout = init_project(tmp_path, with_scaffold=False).layout
    _make_directory(layout, "models")
    result = import_model(layout, _build_residual_net, name="ResNet", parent="/models")

    ids = result.module_node_ids
    by_endpoints = {(e.source_id, e.target_id) for e in iter_edges(layout) if e.type == "data_flow"}

    assert (ids["b.norm"], ids["b.lin"]) in by_endpoints
    assert (ids["b"], ids["head"]) in by_endpoints


def _build_functional_bridge_net() -> tuple[Any, tuple[Any, ...]]:
    """Two Modules separated by a functional reshape (new tensor id)."""
    import torch.nn as nn

    class Net(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.norm = nn.LayerNorm(8)
            self.head = nn.Linear(8, 2)

        def forward(self, x: Any) -> Any:
            x = self.norm(x)
            x = x.reshape(-1, 2, 4).flatten(1)
            return self.head(x)

    return Net(), (torch.randn(3, 8),)


def test_functional_bridge_between_modules_captured(tmp_path: Path) -> None:
    """Module-to-Module flow across a functional reshape still emits an edge."""
    from simulanka.storage.entity_store import iter_edges

    layout = init_project(tmp_path, with_scaffold=False).layout
    _make_directory(layout, "models")
    result = import_model(
        layout, _build_functional_bridge_net, name="Bridge", parent="/models",
    )

    ids = result.module_node_ids
    by_endpoints = {
        (e.source_id, e.target_id)
        for e in iter_edges(layout) if e.type == "data_flow"
    }
    assert (ids["norm"], ids["head"]) in by_endpoints


def _build_structure_only() -> tuple[Any, None]:
    """Build returning ``example_inputs=None`` — the structure-only escape hatch.

    Models whose ``forward`` consumes dict batches / pipeline state can use this
    to register their full ``named_modules()`` tree without faking inputs.
    """
    import torch.nn as nn

    class HardToCall(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.encoder = nn.Linear(8, 8)
            self.head = nn.Linear(8, 2)

        def forward(self, batch: dict[str, Any]) -> Any:  # not called in this mode
            return self.head(self.encoder(batch["x"]))

    return HardToCall(), None


def test_structure_only_import_skips_dataflow(tmp_path: Path) -> None:
    """``example_inputs=None`` commits the module tree but no data_flow edges."""
    from simulanka.storage.entity_store import iter_edges, iter_nodes

    layout = init_project(tmp_path, with_scaffold=False).layout
    _make_directory(layout, "models")
    result = import_model(
        layout, _build_structure_only, name="HardToCall", parent="/models",
    )

    assert set(result.module_node_ids) == {"", "encoder", "head"}
    assert result.data_flow_edge_ids == []
    assert [e for e in iter_edges(layout) if e.type == "data_flow"] == []

    root = next(n for n in iter_nodes(layout) if n.id == result.module_node_ids[""])
    assert root.attrs.get("dataflow_unavailable") is True

    report = run_doctor(layout)
    assert report.ok, [i.model_dump() for i in report.issues]


def test_structure_only_rejects_non_tuple_non_none(tmp_path: Path) -> None:
    """A non-tuple, non-None ``example_inputs`` is still a contract violation."""
    from simulanka.importer import ModelImportError

    def bad_build() -> tuple[Any, Any]:
        import torch.nn as nn
        return nn.Linear(4, 4), "not a tuple"

    layout = init_project(tmp_path, with_scaffold=False).layout
    _make_directory(layout, "models")
    with pytest.raises(ModelImportError):
        import_model(layout, bad_build, name="Bad", parent="/models")
