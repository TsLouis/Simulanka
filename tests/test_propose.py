"""Tests for §13.5.3 agent ghost-edge proposal (`simulanka.propose`).

The pure helpers (forward extraction, reply parsing) run without torch. The
end-to-end test imports a real model and injects a fake opencode runner, so the
parse → map → commit path is exercised deterministically (no network).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from simulanka.propose import (
    GhostEdge,
    ProposeError,
    _extract_forward_source,
    parse_response,
    propose_edges,
)

_FOO_SRC = '''
class Foo:
    def __init__(self) -> None:
        self.a = 1

    def forward(self, x):
        h = self.a(x)
        return self.b(h)


class Bar:
    def something(self):
        return 0
'''


# --- pure: forward extraction ------------------------------------------------

def test_extract_forward_source_found() -> None:
    out = _extract_forward_source(_FOO_SRC, "Foo")
    assert out is not None
    assert out.startswith("def forward")
    assert "self.b(h)" in out


def test_extract_forward_source_missing() -> None:
    assert _extract_forward_source(_FOO_SRC, "Bar") is None  # no forward
    assert _extract_forward_source(_FOO_SRC, "Nope") is None  # no such class
    assert _extract_forward_source("def x(): pass\n", "Foo") is None


def test_extract_forward_prefers_last_top_level_class() -> None:
    # On a same-name redefinition Python binds the *last* class; the extractor
    # must follow suit. The old first-match scan fed the shadowed forward.
    src = (
        "class Net:\n"
        "    def forward(self, x):\n"
        "        return self.old(x)\n"
        "\n"
        "class Net:\n"
        "    def forward(self, x):\n"
        "        return self.new(x)\n"
    )
    out = _extract_forward_source(src, "Net")
    assert out is not None
    assert "self.new(x)" in out and "self.old(x)" not in out


def test_extract_forward_ignores_nested_same_name_class() -> None:
    # A nested helper sharing the class name must not shadow the real top-level
    # module class.
    src = (
        "class Outer:\n"
        "    class Net:\n"
        "        def forward(self, x):\n"
        "            return self.nested(x)\n"
        "\n"
        "class Net:\n"
        "    def forward(self, x):\n"
        "        return self.real(x)\n"
    )
    out = _extract_forward_source(src, "Net")
    assert out is not None
    assert "self.real(x)" in out and "self.nested(x)" not in out


# --- pure: reply parsing -----------------------------------------------------

def test_parse_fenced_block() -> None:
    raw = (
        'Here you go:\n```json\n'
        '[{"src": "a", "dst": "b", "citation": "self.b(self.a(x))"}]\n```\nDone.'
    )
    assert parse_response(raw) == [GhostEdge("a", "b", "self.b(self.a(x))")]


def test_parse_bare_array_in_prose() -> None:
    raw = 'sure [{"src": "a", "dst": "b", "citation": "x"}] thanks'
    out = parse_response(raw)
    assert len(out) == 1 and out[0].src == "a"


def test_parse_garbage_yields_empty() -> None:
    assert parse_response("no json at all") == []
    assert parse_response("```json\n{ not valid }\n```") == []


def test_parse_bracket_in_citation_unfenced() -> None:
    # A `]` inside a citation string (indexing) must not truncate the array.
    raw = '[{"src": "a", "dst": "b", "citation": "h = self.b(x[0])"}]'
    assert parse_response(raw) == [GhostEdge("a", "b", "h = self.b(x[0])")]


def test_parse_array_with_surrounding_prose_brackets() -> None:
    # Brackets in the prose before/after the real array must not defeat parsing
    # (the old first-`[`-to-last-`]` slice silently returned []).
    trailing = 'edges: [{"src": "a", "dst": "b", "citation": "x"}] (see ref[2])'
    assert parse_response(trailing) == [GhostEdge("a", "b", "x")]
    leading = 'ref[1] says: [{"src": "a", "dst": "b", "citation": "x"}]'
    assert parse_response(leading) == [GhostEdge("a", "b", "x")]


def test_parse_drops_malformed_entries() -> None:
    raw = '[{"src": "a", "dst": "b", "citation": "c"}, {"src": 1, "dst": "b"}, "nope"]'
    out = parse_response(raw)
    assert out == [GhostEdge("a", "b", "c")]
    # a missing citation is kept as "" — propose_edges is what skips uncited edges
    assert parse_response('[{"src": "a", "dst": "b"}]')[0].citation == ""


def test_parse_response_captures_out_port_and_slice() -> None:
    # §13.5.6: the model may name which output an edge leaves (`out_port`) and the
    # sub-slice it carries (`slice`). Both optional; absent → None.
    raw = (
        '[{"src": "image_encoder", "dst": "memory_attention", "out_port": "out2", '
        '"slice": "[-1]", "citation": "feats = backbone_out[-1]"}]'
    )
    assert parse_response(raw) == [
        GhostEdge(
            "image_encoder",
            "memory_attention",
            "feats = backbone_out[-1]",
            out_port="out2",
            out_slice="[-1]",
        )
    ]
    # Empty strings are normalised to None, not kept as "".
    blanks = '[{"src": "a", "dst": "b", "citation": "c", "out_port": "", "slice": ""}]'
    assert parse_response(blanks) == [GhostEdge("a", "b", "c")]


def test_parse_response_captures_evidence_locality() -> None:
    raw = (
        '[{"src": "memory_encoder", "dst": "memory_attention", '
        '"evidence_locality": "cross_state", '
        '"citation": "memory = self.memory_encoder(...)"}]'
    )
    assert parse_response(raw) == [
        GhostEdge(
            "memory_encoder",
            "memory_attention",
            "memory = self.memory_encoder(...)",
            evidence_locality="cross_state",
        )
    ]

    invalid = (
        '[{"src": "a", "dst": "b", "evidence_locality": "guessy", '
        '"citation": "x"}]'
    )
    assert parse_response(invalid) == [GhostEdge("a", "b", "x")]


def test_propose_bad_selector_raises_proposeerror(tmp_path: Path) -> None:
    # A typo'd / unresolvable selector must surface as ProposeError (which the
    # CLI catches), not a raw ResolveError traceback.
    from simulanka.layout.project import init_project

    layout = init_project(tmp_path, with_scaffold=False).layout
    with pytest.raises(ProposeError):
        propose_edges(layout, "no_such_model", runner=lambda _p, _m: "[]")


# --- end-to-end with injected runner ----------------------------------------

def _build_tiny_mlp() -> tuple[Any, tuple[Any, ...]]:
    import torch
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


def test_propose_edges_end_to_end(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    from simulanka.importer import import_model
    from simulanka.kernel.apply import apply_patch
    from simulanka.kernel.intent import CreateNodeOp, PatchIntent
    from simulanka.layout.project import init_project
    from simulanka.storage.entity_store import iter_edges

    layout = init_project(tmp_path, with_scaffold=False).layout
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="models")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    import_model(layout, _build_tiny_mlp, name="TinyMLP", parent="/models")

    captured: dict[str, str] = {}

    def fake_runner(prompt: str, model: str) -> str:
        captured["prompt"] = prompt
        return """```json
[
  {"src": "b1", "dst": "b2", "citation": "h = self.b2(h)"},
  {"src": "b2", "dst": "head", "evidence_locality": "in_method", "citation": "return self.head(h)"},
  {"src": "b1", "dst": "ghost_module", "citation": "x"},
  {"src": "head", "dst": "b1", "citation": ""}
]
```"""

    result = propose_edges(layout, "TinyMLP", runner=fake_runner)

    # Prompt carried the legal vocabulary + the real forward.
    assert "b1" in captured["prompt"] and "head" in captured["prompt"]
    assert "def forward" in captured["prompt"]

    # Two cited, in-vocabulary edges land; the unknown-dst and the uncited ones
    # are skipped (少而准 enforced in code, not just prompt).
    assert {(g.src, g.dst) for g in result.proposed} == {("b1", "b2"), ("b2", "head")}
    assert len(result.edge_ids) == 2
    skipped_reasons = {(g.src, g.dst): r for g, r in result.skipped}
    assert "ghost_module" in skipped_reasons[("b1", "ghost_module")]
    assert "citation" in skipped_reasons[("head", "b1")]

    # Every committed ghost edge carries the §13.5.3 attrs.
    ghosts = [e for e in iter_edges(layout) if e.attrs.get("source") == "agent"]
    assert len(ghosts) == 2
    for e in ghosts:
        assert e.type == "data_flow"
        assert e.attrs["status"] == "proposed"
        assert e.attrs["verdict"] == "unconfirmed"
        assert e.attrs["citation"]
    assert any(e.attrs.get("evidence_locality") == "in_method" for e in ghosts)


def test_propose_edges_dedups_across_runs(tmp_path: Path) -> None:
    # Re-running `propose` on the same graph must not pile up duplicate ghosts;
    # dedup is in propose (the kernel doesn't dedup data_flow).
    pytest.importorskip("torch")
    from simulanka.importer import import_model
    from simulanka.kernel.apply import apply_patch
    from simulanka.kernel.intent import CreateNodeOp, PatchIntent
    from simulanka.layout.project import init_project
    from simulanka.storage.entity_store import iter_edges

    layout = init_project(tmp_path, with_scaffold=False).layout
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="models")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    import_model(layout, _build_tiny_mlp, name="TinyMLP", parent="/models")

    def runner(_p: str, _m: str) -> str:
        return '[{"src": "b1", "dst": "b2", "citation": "h = self.b2(h)"}]'

    first = propose_edges(layout, "TinyMLP", runner=runner)
    assert len(first.edge_ids) == 1

    second = propose_edges(layout, "TinyMLP", runner=runner)
    assert second.edge_ids == []
    assert any("already" in reason for _g, reason in second.skipped)
    agent_edges = [e for e in iter_edges(layout) if e.attrs.get("source") == "agent"]
    assert len(agent_edges) == 1


def _build_multi_out() -> tuple[Any, tuple[Any, ...]]:
    """A model whose `encoder` child returns a 2-tuple, so the importer gives it
    two structural output ports (`out`, `out1`). The top forward routes each
    output to a different head — the §13.5.6 multi-output shape, in miniature."""
    import torch
    import torch.nn as nn

    class Encoder(nn.Module):
        def __init__(self, d: int) -> None:
            super().__init__()
            self.deep = nn.Linear(d, d)
            self.shallow = nn.Linear(d, d)

        def forward(self, x: Any) -> Any:
            return self.deep(x), self.shallow(x)

    class TopModel(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.encoder = Encoder(8)
            self.head_deep = nn.Linear(8, 2)
            self.head_shallow = nn.Linear(8, 2)

        def forward(self, x: Any) -> Any:
            deep, shallow = self.encoder(x)
            return self.head_deep(deep) + self.head_shallow(shallow)

    return TopModel(), (torch.randn(2, 8),)


def test_propose_edges_multi_output_ports(tmp_path: Path) -> None:
    # §13.5.6: an edge leaves a *specific* structural output port (resolved from
    # the model's `out_port`), and a sub-slice rides the edge as `output_slice` —
    # so `encoder`'s two outputs to two heads stay distinct, not smeared onto one.
    pytest.importorskip("torch")
    from simulanka.importer import import_model
    from simulanka.kernel.apply import apply_patch
    from simulanka.kernel.intent import CreateNodeOp, PatchIntent
    from simulanka.layout.project import init_project
    from simulanka.storage.entity_store import iter_edges, iter_nodes, iter_ports

    layout = init_project(tmp_path, with_scaffold=False).layout
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="models")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    import_model(layout, _build_multi_out, name="TopModel", parent="/models")

    # Sanity: the importer really gave `encoder` two output ports.
    enc_id = next(n.id for n in iter_nodes(layout) if n.name == "encoder")
    enc_out = sorted(
        p.name for p in iter_ports(layout) if p.node_id == enc_id and p.direction == "out"
    )
    assert enc_out == ["out", "out1"]

    def fake_runner(_p: str, _m: str) -> str:
        return (
            '[{"src": "encoder", "dst": "head_deep", "out_port": "out", '
            '"citation": "deep, shallow = self.encoder(x)"},'
            '{"src": "encoder", "dst": "head_shallow", "out_port": "out1", '
            '"slice": "shallow", "citation": "self.head_shallow(shallow)"}]'
        )

    result = propose_edges(layout, "TopModel", runner=fake_runner)
    assert len(result.edge_ids) == 2

    port_name = {p.id: p.name for p in iter_ports(layout)}
    by_target = {
        e.target_id: e
        for e in iter_edges(layout)
        if e.attrs.get("source") == "agent"
    }
    head_deep_id = next(n.id for n in iter_nodes(layout) if n.name == "head_deep")
    head_shallow_id = next(n.id for n in iter_nodes(layout) if n.name == "head_shallow")

    # The deep edge leaves encoder.out, the shallow edge leaves encoder.out1 —
    # they are NOT both smeared onto `out`.
    deep_edge = by_target[head_deep_id]
    shallow_edge = by_target[head_shallow_id]
    deep_port, shallow_port = deep_edge.source_port_id, shallow_edge.source_port_id
    assert deep_port is not None and shallow_port is not None
    assert deep_edge.source_id == enc_id and shallow_edge.source_id == enc_id
    assert port_name[deep_port] == "out"
    assert port_name[shallow_port] == "out1"
    # The sub-slice rides the edge; the deep edge has none.
    assert shallow_edge.attrs.get("output_slice") == "shallow"
    assert "output_slice" not in deep_edge.attrs
