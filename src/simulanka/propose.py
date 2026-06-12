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
from simulanka.schema.entities import Port
from simulanka.storage.entity_store import iter_edges, iter_nodes, iter_ports

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
    with the ``forward`` source line the model cited as evidence.

    ``out_port`` / ``out_slice`` carry §13.5.6's multi-output split: ``out_port``
    names which structural output of ``src`` the edge leaves (the port ``name``
    like ``out2`` or its ``label`` like ``backbone_fpn``); ``out_slice`` is the
    sub-part of that output the edge actually carries (``[-1]`` / ``[:-1]``) when
    one output feeds several consumers by slicing. ``evidence_locality`` is the
    §13.5.4 confidence label: ``in_method``, ``cross_method``, or
    ``cross_state``. All optional — a clean single-output module leaves the
    output fields unset and the edge attaches to ``out``."""

    src: str
    dst: str
    citation: str
    out_port: str | None = None
    out_slice: str | None = None
    evidence_locality: str | None = None


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

    out_ports = _output_ports(layout, children)
    prompt = build_prompt(str(class_name), forward_src, sorted(children), out_ports)
    if runner is not None:
        raw = runner(prompt, model)
    else:
        raw = _run_opencode(prompt, model, timeout=timeout)
    ghosts = parse_response(raw)

    # Ghost edges already laid down by a prior `propose` run on this graph, keyed
    # by (source_id, target_id) — re-running must update/skip, not pile up dupes.
    # The kernel doesn't dedup `data_flow`, so we do it here. (source_id is the
    # node owning the source port, see apply.py.) Node-pair (not port) granularity
    # on purpose: once any edge between two modules exists, don't re-propose it —
    # the human may have verified/edited it (edge-attr re-proposal is deferred).
    existing: set[tuple[str, str]] = {
        (e.source_id, e.target_id)
        for e in iter_edges(layout)
        if e.type == "data_flow" and e.attrs.get("source") == "agent"
    }

    ops: list[IntentOp] = []
    applied: list[GhostEdge] = []
    skipped: list[tuple[GhostEdge, str]] = []
    # Within-run dedup keys on the resolved output port too, so one module feeding
    # two different outputs to the same consumer (§13.5.6) survives as two edges.
    seen: set[tuple[str, str, str]] = set()
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
        out_name = _resolve_out_port(g.out_port, out_ports[g.src])
        if (g.src, out_name, g.dst) in seen:
            skipped.append((g, "duplicate"))
            continue
        if (children[g.src], children[g.dst]) in existing:
            skipped.append((g, "already a ghost edge from a previous run"))
            continue
        seen.add((g.src, out_name, g.dst))
        attrs: dict[str, str] = {
            "source": "agent",
            "status": "proposed",
            "verdict": "unconfirmed",
            "citation": g.citation,
        }
        # §13.5.6 D4: the slice that distinguishes which output this edge carries
        # rides the edge, not a new port — importer/schema stay untouched.
        if g.out_slice:
            attrs["output_slice"] = g.out_slice
        if g.evidence_locality:
            attrs["evidence_locality"] = g.evidence_locality
        ops.append(
            CreateEdgeOp(
                type="data_flow",
                source=f"{children[g.src]}.{out_name}",
                target=f"{children[g.dst]}.in",
                attrs=attrs,
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
    file on disk (no import needed).

    An ``nn.Module`` is defined at module top level, so a top-level class wins
    over a nested same-named helper, and on a top-level redefinition the *last*
    one wins — matching Python's own name binding. Only when no top-level class
    matches do we fall back to the first nested definition. (The old plain
    first-``ast.walk``-match could feed a shadowed/nested class's forward.)"""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return None
    top_level = [
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name
    ]
    cls = top_level[-1] if top_level else next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name),
        None,
    )
    if cls is None:
        return None
    for item in cls.body:
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


def _output_ports(
    layout: ProjectLayout, children: dict[str, str]
) -> dict[str, list[Port]]:
    """Map each direct child's **name** → its output ports, slot order (``out``,
    ``out1``, …). Used to give the model an output-port vocabulary and to resolve
    its ``out_port`` choice back to a structural port name."""
    name_by_id = {node_id: name for name, node_id in children.items()}
    out: dict[str, list[Port]] = {name: [] for name in children}
    for p in iter_ports(layout):
        if p.direction == "out" and p.node_id in name_by_id:
            out[name_by_id[p.node_id]].append(p)
    for ports in out.values():
        ports.sort(key=lambda p: p.name)
    return out


def _resolve_out_port(alias: str | None, ports: list[Port]) -> str:
    """Resolve the model's ``out_port`` choice to a structural port name. ``alias``
    may be the port ``name`` (``out2``) or its semantic ``label`` (``backbone_fpn``);
    an unknown or absent alias falls back to the primary ``out`` slot."""
    if alias:
        for p in ports:
            if p.name == alias or p.attrs.get("label") == alias:
                return p.name
    return "out"


def _port_vocab(ports: list[Port]) -> str:
    """Render one module's output ports as ``out (label), out1 (label2)`` for the
    prompt, so the model can name which output an edge leaves from."""
    parts = []
    for p in ports:
        label = p.attrs.get("label")
        parts.append(f"{p.name} ({label})" if label else p.name)
    return ", ".join(parts) if parts else "out"


def build_prompt(
    class_name: str,
    forward_src: str,
    child_names: list[str],
    out_ports: dict[str, list[Port]],
) -> str:
    """A rough (spike) prompt asking for cited data-flow edges between the named
    submodules. Wording is throwaway — see the module docstring."""
    names = "\n".join(
        f"  - {n}  (outputs: {_port_vocab(out_ports.get(n, []))})" for n in child_names
    )
    return (
        f"You are reading the `forward` method of a PyTorch module `{class_name}`.\n"
        "Identify the DATA-FLOW edges between its direct submodules: which "
        "submodule's output is fed (directly or via reshape/cat/etc.) into which "
        "other submodule's input, as written in this code.\n\n"
        "Rules:\n"
        f"- Endpoints MUST be from this exact list of submodules (with their "
        f"output ports):\n{names}\n"
        "- Only include an edge if you can point to the line of code that shows "
        "it. Put that line (verbatim) in `citation`.\n"
        "- Set `out_port` to which output of `src` the edge leaves from (the port "
        "name like `out2`, or its label like `backbone_fpn`). Omit for a "
        "single-output module.\n"
        "- If the edge carries only a SUB-PART of that output (a slice/index such "
        "as `x[-1]` or `x[:-1]`), put that slice in `slice`. This is how one "
        "output feeding several consumers stays distinguishable.\n"
        "- Set `evidence_locality` to `in_method`, `cross_method`, or "
        "`cross_state`: in_method means the evidence is local to this method; "
        "cross_method means you followed another method call; cross_state means "
        "the flow passes through object state, cache, memory bank, or a later call.\n"
        "- If you are not sure, leave the edge out. Fewer, certain edges are "
        "better than guesses.\n"
        "- Do NOT invent submodule names not in the list.\n\n"
        "Output ONLY a JSON array, no prose, like:\n"
        '[{"src": "image_encoder", "dst": "memory_attention", "out_port": "out2", '
        '"slice": "[-1]", "evidence_locality": "cross_state", '
        '"citation": "vision_feats = backbone_out[-1]"}]\n\n'
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
        op = item.get("out_port")
        sl = item.get("slice")
        locality = item.get("evidence_locality")
        out.append(
            GhostEdge(
                src=src,
                dst=dst,
                citation=cite,
                out_port=op if isinstance(op, str) and op else None,
                out_slice=sl if isinstance(sl, str) and sl else None,
                evidence_locality=(
                    locality
                    if isinstance(locality, str)
                    and locality in ("in_method", "cross_method", "cross_state")
                    else None
                ),
            )
        )
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
