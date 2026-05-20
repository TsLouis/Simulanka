"""Tests for the Model Explorer JSON exporter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

torch = pytest.importorskip("torch")

import torch.nn as nn  # noqa: E402

from simulanka.exporter import to_model_explorer  # noqa: E402
from simulanka.importer import import_model  # noqa: E402
from simulanka.kernel.apply import apply_patch  # noqa: E402
from simulanka.kernel.intent import CreateNodeOp, PatchIntent  # noqa: E402
from simulanka.layout.project import ProjectLayout, init_project  # noqa: E402


def _make_directory(layout: ProjectLayout, name: str) -> None:
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name=name)],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )


def _build_tiny() -> tuple[Any, tuple[Any, ...]]:
    class Block(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lin = nn.Linear(4, 4)
            self.act = nn.ReLU()

        def forward(self, x: Any) -> Any:
            return self.act(self.lin(x))

    class TinyNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.b1 = Block()
            self.head = nn.Linear(4, 2)

        def forward(self, x: Any) -> Any:
            return self.head(self.b1(x))

    return TinyNet(), (torch.randn(2, 4),)


def _only_graph(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract the single inner Graph from the `{"graphs": [...]}` wire shape."""
    assert "graphs" in payload
    assert len(payload["graphs"]) == 1
    return payload["graphs"][0]  # type: ignore[no-any-return]


def test_exports_hierarchy_namespace_and_label(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _make_directory(layout, "models")
    import_model(layout, _build_tiny, name="TinyNet", parent="/models")

    payload = to_model_explorer(layout, "/models/TinyNet")

    g = _only_graph(payload)
    assert g["id"] == "TinyNet"
    nodes = {n["id"]: n for n in g["nodes"]}

    # Every module fqn except the root model itself is present.
    assert set(nodes) == {"b1", "b1.lin", "b1.act", "head"}

    # Top-level child has empty namespace; nested children carry slash-separated.
    assert nodes["b1"]["namespace"] == ""
    assert nodes["b1.lin"]["namespace"] == "b1"
    assert nodes["b1.act"]["namespace"] == "b1"

    # Label is "leaf (class)".
    assert nodes["b1.lin"]["label"] == "lin (Linear)"
    assert nodes["head"]["label"] == "head (Linear)"


def test_exports_incoming_edges_from_data_flow(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _make_directory(layout, "models")
    import_model(layout, _build_tiny, name="TinyNet", parent="/models")

    payload = to_model_explorer(layout, "/models/TinyNet")
    nodes = {n["id"]: n for n in _only_graph(payload)["nodes"]}

    # b1.lin → b1.act inside the block; b1 → head at top level.
    act_incoming = {e["sourceNodeId"] for e in nodes["b1.act"]["incomingEdges"]}
    head_incoming = {e["sourceNodeId"] for e in nodes["head"]["incomingEdges"]}
    assert "b1.lin" in act_incoming
    assert "b1" in head_incoming


def test_exports_structure_only_root_has_empty_incoming_edges(tmp_path: Path) -> None:
    """Structure-only imports produce no data_flow edges, so every node's
    incomingEdges list is present but empty (Model Explorer's frontend
    expects the key on every node)."""
    layout = init_project(tmp_path, with_scaffold=False).layout
    _make_directory(layout, "models")

    def build_structure_only() -> tuple[Any, None]:
        return _build_tiny()[0], None

    import_model(
        layout, build_structure_only, name="TinyNetStruct", parent="/models",
    )

    payload = to_model_explorer(layout, "/models/TinyNetStruct")
    for n in _only_graph(payload)["nodes"]:
        assert n["incomingEdges"] == []


def test_rejects_non_model_selector(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _make_directory(layout, "models")
    with pytest.raises(ValueError, match="expected a `model` node"):
        to_model_explorer(layout, "/models")
