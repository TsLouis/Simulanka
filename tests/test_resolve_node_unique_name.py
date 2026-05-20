"""resolve_node should fall back to a unique-name lookup, like resolve_port."""

from __future__ import annotations

from pathlib import Path

import pytest

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.kernel.resolver import ResolveError, resolve_node
from simulanka.layout import init_project


def _add_dir(layout, parent_id: str | None, name: str) -> str:  # type: ignore[no-untyped-def]
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name=name, parent=parent_id, attrs={})],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )
    return receipt.nodes[0]


def test_bare_name_resolves_when_unique(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    root_id = _add_dir(layout, None, "research")
    _add_dir(layout, root_id, "exp1")

    # Bare name works — previously this raised ResolveError.
    node = resolve_node(layout, "exp1")
    assert node.name == "exp1"


def test_bare_name_ambiguous_lists_candidates(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    a = _add_dir(layout, None, "a")
    b = _add_dir(layout, None, "b")
    _add_dir(layout, a, "shared")
    _add_dir(layout, b, "shared")

    with pytest.raises(ResolveError) as exc:
        resolve_node(layout, "shared")
    msg = str(exc.value)
    assert "ambiguous" in msg
    # Both candidate ids should appear so the user knows what to disambiguate.
    assert msg.count("nod_") >= 2


def test_bare_name_unknown_says_so(tmp_path: Path) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    with pytest.raises(ResolveError, match="No node named"):
        resolve_node(layout, "does_not_exist")


def test_absolute_path_still_works(tmp_path: Path) -> None:
    """Path resolution must still take precedence so users can disambiguate."""
    layout = init_project(tmp_path, with_scaffold=False).layout
    a = _add_dir(layout, None, "a")
    b = _add_dir(layout, None, "b")
    a_shared = _add_dir(layout, a, "shared")
    _add_dir(layout, b, "shared")

    node = resolve_node(layout, "/a/shared")
    assert node.id == a_shared
