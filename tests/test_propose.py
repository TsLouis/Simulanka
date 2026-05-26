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
  {"src": "b2", "dst": "head", "citation": "return self.head(h)"},
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
