"""§13.5.3 agent edge proposal — "agent reads ``forward()`` and proposes ghost edges".

This is the spike loop (§13.5.3, Q7 task B): read a model node's top-level
``forward`` source, ask a (free) model which submodules feed which, and lay the
answers down as *ghost* ``data_flow`` edges — ``source="agent"``,
``status="proposed"``, ``verdict="unconfirmed"`` — for the human to confirm.

Deliberately **not** routed through ``agent/wrapper.py``: that layer snapshots a
workspace diff and never parses agent output. Here we *do* parse a structured
reply into edges, so it is its own thin module.

Two §13.5.3 disciplines are enforced here, not left to prompt wording:

* **少而准 (few-but-accurate).** Only edges between known direct children, and
  only edges the model attaches a non-empty ``citation`` to, are laid down. An
  edge the model can't point at a ``forward`` line for is a guess, and a guess
  is skipped — "宁可漏不可错".
* **No auto-confirm.** Every ghost is born ``verdict="unconfirmed"``. The
  human/agent verify step (deferred) is what ever turns it into
  ``correct``/``wrong``/``disputed``.

The prompt is intentionally rough; prompt wording, citation format, and agent
self-eval belong to the later agent-engineering phase, not this spike.
"""

from __future__ import annotations

import ast
import json
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from simulanka.kernel.apply import apply_patch_now
from simulanka.kernel.intent import CreateEdgeOp, IntentOp
from simulanka.kernel.resolver import ResolveError, resolve_node
from simulanka.layout.project import ProjectLayout
from simulanka.storage.entity_store import iter_nodes

DEFAULT_MODEL = "opencode/deepseek-v4-flash-free"
DEFAULT_TIMEOUT = 180.0

# (prompt, model) → raw model reply text. Injectable so the parse/map logic is
# unit-tested without a network round-trip.
OpencodeRunner = Callable[[str, str], str]


class ProposeError(RuntimeError):
    """Raised when edges cannot be proposed (bad node, unreadable source, ...)."""


@dataclass(frozen=True)
class GhostEdge:
    """One proposed data-flow relation between two direct-child attribute names,
    with the ``forward`` source line the model cited as evidence."""

    src: str
    dst: str
    citation: str


@dataclass(frozen=True)
class ProposeResult:
    model_node_id: str
    raw_response: str
    proposed: list[GhostEdge]
    edge_ids: list[str]
    skipped: list[tuple[GhostEdge, str]] = field(default_factory=list)


def propose_edges(
    layout: ProjectLayout,
    model_selector: str,
    *,
    model: str = DEFAULT_MODEL,
    actor: str = "agent:propose",
    timeout: float = DEFAULT_TIMEOUT,
    runner: OpencodeRunner | None = None,
) -> ProposeResult:
    """Read the model's ``forward`` source, ask *model* for data-flow edges, and
    commit the cited ones as ghost ``data_flow`` edges. Returns what was applied
    and what was skipped (with reasons)."""
    try:
        root = resolve_node(layout, model_selector)
    except ResolveError as exc:
        raise ProposeError(f"cannot resolve model {model_selector!r}: {exc}") from exc
    if root.type != "model":
        raise ProposeError(
            f"`{model_selector}` is a {root.type!r} node, not a 'model'. "
            "Ghost proposal reads a top-level model's forward()."
        )
    source_file = root.attrs.get("source_file")
    class_name = root.attrs.get("class_name")
    if not source_file or not class_name:
        raise ProposeError(
            f"model node {root.id} lacks source_file/class_name "
            "(re-import with a build that has Python source)."
        )

    try:
        source_text = Path(str(source_file)).read_text(encoding="utf-8")
    except OSError as exc:
        raise ProposeError(f"cannot read source_file {source_file!r}: {exc}") from exc

    forward_src = _extract_forward_source(source_text, str(class_name))
    if forward_src is None:
        raise ProposeError(
            f"no `forward` method found for class {class_name!r} in {source_file}."
        )

    children = _direct_children(layout, root.id)
    if not children:
        raise ProposeError(f"model node {root.id} has no submodule children to connect.")

    prompt = build_prompt(str(class_name), forward_src, sorted(children))
    if runner is not None:
        raw = runner(prompt, model)
    else:
        raw = _run_opencode(prompt, model, timeout=timeout)
    ghosts = parse_response(raw)

    ops: list[IntentOp] = []
    applied: list[GhostEdge] = []
    skipped: list[tuple[GhostEdge, str]] = []
    seen: set[tuple[str, str]] = set()
    for g in ghosts:
        if not g.citation.strip():
            skipped.append((g, "no citation — a guess, not a cited edge"))
            continue
        if g.src not in children:
            skipped.append((g, f"unknown src module {g.src!r}"))
            continue
        if g.dst not in children:
            skipped.append((g, f"unknown dst module {g.dst!r}"))
            continue
        if g.src == g.dst:
            skipped.append((g, "self-loop"))
            continue
        if (g.src, g.dst) in seen:
            skipped.append((g, "duplicate"))
            continue
        seen.add((g.src, g.dst))
        ops.append(
            CreateEdgeOp(
                type="data_flow",
                source=f"{children[g.src]}.out",
                target=f"{children[g.dst]}.in",
                attrs={
                    "source": "agent",
                    "status": "proposed",
                    "verdict": "unconfirmed",
                    "citation": g.citation,
                },
            ),
        )
        applied.append(g)

    edge_ids: list[str] = []
    if ops:
        receipt = apply_patch_now(
            layout,
            ops=ops,
            actor=actor,
            note=f"propose_edges: {len(ops)} ghost edge(s) on {root.name}",
        )
        edge_ids = receipt.edges

    return ProposeResult(
        model_node_id=root.id,
        raw_response=raw,
        proposed=applied,
        edge_ids=edge_ids,
        skipped=skipped,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_forward_source(source_text: str, class_name: str) -> str | None:
    """Return the source of ``class_name``'s ``forward`` method, read from the
    file on disk (no import needed). First matching class wins."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == "forward"
                ):
                    segment = ast.get_source_segment(source_text, item)
                    if segment is not None:
                        return segment
    return None


def _direct_children(layout: ProjectLayout, parent_id: str) -> dict[str, str]:
    """Map ``submodule attribute name → node id`` for the model's direct module
    children. Names are sibling-unique (kernel-enforced), so this is 1:1, and a
    direct child's name equals its ``self.<name>`` attribute in ``forward``."""
    return {
        n.name: n.id
        for n in iter_nodes(layout)
        if n.parent_id == parent_id and n.type == "module"
    }


def build_prompt(class_name: str, forward_src: str, child_names: list[str]) -> str:
    """A rough (spike) prompt asking for cited data-flow edges between the named
    submodules. Wording is throwaway — see the module docstring."""
    names = "\n".join(f"  - {n}" for n in child_names)
    return (
        f"You are reading the `forward` method of a PyTorch module `{class_name}`.\n"
        "Identify the DATA-FLOW edges between its direct submodules: which "
        "submodule's output is fed (directly or via reshape/cat/etc.) into which "
        "other submodule's input, as written in this code.\n\n"
        "Rules:\n"
        f"- Endpoints MUST be from this exact list of submodule names:\n{names}\n"
        "- Only include an edge if you can point to the line of code that shows "
        "it. Put that line (verbatim) in `citation`.\n"
        "- If you are not sure, leave the edge out. Fewer, certain edges are "
        "better than guesses.\n"
        "- Do NOT invent submodule names not in the list.\n\n"
        "Output ONLY a JSON array, no prose, like:\n"
        '[{"src": "encoder", "dst": "decoder", '
        '"citation": "z = self.decoder(self.encoder(x))"}]\n\n'
        "forward source:\n"
        "```python\n"
        f"{forward_src}\n"
        "```\n"
    )


def parse_response(raw: str) -> list[GhostEdge]:
    """Pull a JSON array of ``{src, dst, citation}`` out of a model reply.

    Tolerant of the common wrappers — a ```json fence, a bare array, or an array
    with surrounding prose. The reply format is not a contract, so we try every
    balanced ``[...]`` region in the text and return the first that parses into
    at least one ``{src, dst}`` object. Malformed entries are dropped.

    Naive first-``[``-to-last-``]`` slicing was wrong: a ``]`` in a citation
    (``x[0]``) or a bracket in surrounding prose (``see ref[2]``) made the slice
    unparseable and silently yielded zero edges."""
    for candidate in _balanced_arrays(raw):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list):
            continue
        edges = _coerce_edges(data)
        if edges:
            return edges
    return []


def _coerce_edges(data: list[object]) -> list[GhostEdge]:
    """Turn a parsed JSON list into GhostEdges, dropping malformed entries."""
    out: list[GhostEdge] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        src, dst = item.get("src"), item.get("dst")
        if not isinstance(src, str) or not isinstance(dst, str):
            continue
        citation = item.get("citation")
        cite = citation if isinstance(citation, str) else ""
        out.append(GhostEdge(src=src, dst=dst, citation=cite))
    return out


def _balanced_arrays(raw: str) -> Iterator[str]:
    """Yield each balanced ``[...]`` region in *raw*, in order of opening bracket.

    String-aware: brackets inside JSON string literals (citations, code lines)
    don't affect nesting, and nested arrays are kept whole. Yielding from every
    ``[`` lets the caller skip a leading prose bracket that isn't the edge array."""
    for i, ch in enumerate(raw):
        if ch != "[":
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, len(raw)):
            c = raw[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    yield raw[i : j + 1]
                    break


def _run_opencode(prompt: str, model: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Single-shot `opencode run` call, returning stdout (the model's reply).

    ``--print-logs`` is required: without it opencode renders a TUI spinner and
    hangs forever on a non-TTY pipe. With it, logs go to stderr and stdout is
    just the model's reply.
    """
    try:
        proc = subprocess.run(
            ["opencode", "run", "--print-logs", "-m", model, prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ProposeError("`opencode` CLI not found on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProposeError(f"opencode timed out after {timeout}s.") from exc
    if proc.returncode != 0:
        raise ProposeError(
            f"opencode exited {proc.returncode}: {proc.stderr.strip()[:500]}"
        )
    return proc.stdout
