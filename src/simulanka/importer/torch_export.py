"""Import a PyTorch ``nn.Module`` into the graph kernel via forward hooks.

The importer produces a structural view that matches how the researcher wrote
the model:

* **Module hierarchy** comes from ``model.named_modules()`` — one ``model`` node
  for the root and one ``module`` node per non-root submodule.
* **Data flow** comes from a real forward pass under module hooks *plus* a
  ``TorchDispatchMode`` that intercepts every aten op. Each tensor carries a
  producer **set** (which modules' outputs it descends from); aten ops merge
  inputs' producer sets into outputs; module hooks emit an edge at every
  module-boundary crossing and reset the boundary tensor's producer to that
  module. Producer sets propagate through aten ops, so lineage survives
  functional bridges (``+``, ``cat``, ``reshape``, ``window_partition``) that
  have no ``nn_module_stack`` and would otherwise be lost. A leaf-level edge
  ``A.fqn -> B.fqn`` is then rolled up to the first diverging ancestor pair
  (so ``b1.lin -> b2.lin`` becomes ``b1 -> b2``, while ``b1.lin -> b1.act``
  stays at leaf granularity).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import CreateEdgeOp, CreateNodeOp, CreatePortOp, PatchIntent
from simulanka.layout.project import ProjectLayout

if TYPE_CHECKING:  # pragma: no cover
    import torch
    import torch.nn as nn

BuildFn = Callable[[], "tuple[nn.Module, tuple[Any, ...] | None]"]


class ImportError(RuntimeError):
    """Raised when the model cannot be imported (build failure, trace failure, ...)."""


@dataclass(frozen=True)
class ImportResult:
    model_node_id: str
    module_node_ids: dict[str, str]  # fqn ("" for root) → node id
    data_flow_edge_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def import_model(
    layout: ProjectLayout,
    build_fn: BuildFn,
    *,
    name: str,
    parent: str | None = None,
    actor: str = "importer:torch_export",
) -> ImportResult:
    """Import a PyTorch model into the graph.

    Args:
        layout: target project layout.
        build_fn: callable returning ``(model, example_inputs)``. ``example_inputs``
            is a tuple suitable as positional args to ``model(*example_inputs)``,
            **or** ``None`` to skip the forward-pass data-flow trace and import
            the module hierarchy only. Structure-only mode is the escape hatch
            for top-level models whose ``forward`` consumes hard-to-synthesise
            inputs (dict batches, video state, pipeline scaffolding). The root
            ``model`` node is then stamped with ``dataflow_unavailable=true``
            and zero ``data_flow`` edges are emitted.
        name: name of the root ``model`` node (must not contain ``.`` or ``/``).
        parent: selector for the directory under which the model is placed. If
            ``None``, the model becomes a root-level node.
        actor: actor string recorded in the commit events.
    """
    if "." in name or "/" in name:
        raise ImportError(f"name {name!r} must not contain '.' or '/'.")

    torch = _require_torch()

    try:
        built = build_fn()
    except Exception as exc:  # noqa: BLE001 — surface any build failure
        raise ImportError(f"build_fn raised: {exc!r}") from exc

    if (
        not isinstance(built, tuple)
        or len(built) != 2
        or not isinstance(built[0], torch.nn.Module)
    ):
        raise ImportError(
            "build_fn must return (nn.Module, example_inputs_tuple); "
            f"got {type(built).__name__}"
        )
    model, example_inputs = built
    if example_inputs is not None and not isinstance(example_inputs, tuple):
        raise ImportError(
            "example_inputs must be a tuple of positional args, or None for "
            "structure-only import. Wrap a single tensor as `(tensor,)`."
        )

    # 1. Hierarchy via named_modules().
    named = list(model.named_modules())
    # Build a map fqn → module for attrs.
    by_fqn = {fqn: mod for fqn, mod in named}

    # 2. Commit root model node.
    root_path = _join_path(parent, name)
    root_attrs: dict[str, Any] = {
        "class_name": type(model).__name__,
        "num_params": _count_params(model),
        "fqn": "",
    }
    if example_inputs is None:
        root_attrs["dataflow_unavailable"] = True
    model_id = _commit_one_node(
        layout,
        CreateNodeOp(
            type="model",
            name=name,
            parent=parent,
            attrs=root_attrs,
        ),
        actor=actor,
        note=f"import_model: root {name}",
    )
    _commit_io_ports(layout, root_path, actor=actor)

    fqn_to_id: dict[str, str] = {"": model_id}

    # 3. Commit submodule nodes in BFS order (depth ascending) so parents
    # are already on disk when their children resolve.
    submodule_fqns = sorted(
        (fqn for fqn, _ in named if fqn != ""),
        key=lambda f: (f.count("."), f),
    )
    for fqn in submodule_fqns:
        mod = by_fqn[fqn]
        parent_fqn, leaf = _split_fqn(fqn)
        node_id = _commit_one_node(
            layout,
            CreateNodeOp(
                type="module",
                name=leaf,
                parent=_fqn_to_selector(root_path, parent_fqn),
                attrs={
                    "class_name": type(mod).__name__,
                    "num_params": _count_params(mod, recurse=False),
                    "fqn": fqn,
                },
            ),
            actor=actor,
            note=f"import_model: {fqn}",
        )
        fqn_to_id[fqn] = node_id
        _commit_io_ports(
            layout, _fqn_to_selector(root_path, fqn), actor=actor,
        )

    # Structure-only mode: no forward pass, no data_flow edges.
    if example_inputs is None:
        return ImportResult(
            model_node_id=model_id,
            module_node_ids=fqn_to_id,
            data_flow_edge_ids=[],
        )

    # 4. Trace data flow via a real forward pass under hooks.
    try:
        leaf_edges = _collect_leaf_edges(model, example_inputs)
    except Exception as exc:  # noqa: BLE001 — surface forward-pass failures
        raise ImportError(f"forward-hook trace failed: {exc!r}") from exc

    # 5. Roll up to diverging-ancestor pairs and dedupe.
    peer_edges: set[tuple[str, str]] = set()
    for src_fqn, tgt_fqn in leaf_edges:
        if src_fqn not in fqn_to_id or tgt_fqn not in fqn_to_id:
            continue
        pair = _diverging_ancestors(src_fqn, tgt_fqn)
        if pair is not None:
            peer_edges.add(pair)

    # 6. Commit data_flow edges. One patch per edge keeps the event log
    # informative; volume is O(#peer-relations), typically small.
    edge_ids: list[str] = []
    for src, tgt in sorted(peer_edges):
        receipt = apply_patch(
            layout,
            PatchIntent(
                ops=[
                    CreateEdgeOp(
                        type="data_flow",
                        source=_fqn_to_selector(root_path, src) + ".out",
                        target=_fqn_to_selector(root_path, tgt) + ".in",
                    ),
                ],
                actor=actor,
                base_graph_version=layout.load_manifest().graph_version,
                note=f"import_model: data_flow {src} -> {tgt}",
            ),
        )
        edge_ids.extend(receipt.edges)

    return ImportResult(
        model_node_id=model_id,
        module_node_ids=fqn_to_id,
        data_flow_edge_ids=edge_ids,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_torch() -> Any:
    try:
        return importlib.import_module("torch")
    except ImportError as exc:  # pragma: no cover — exercised only without torch
        raise ImportError(
            "torch is required for the importer. Install with "
            "`pip install simulanka[torch]` or `pip install torch>=2.4`."
        ) from exc


def _count_params(module: Any, *, recurse: bool = True) -> int:
    return sum(p.numel() for p in module.parameters(recurse=recurse))


def _split_fqn(fqn: str) -> tuple[str, str]:
    """Return ``(parent_fqn, leaf_name)``. ``parent_fqn`` is ``""`` for top-level."""
    if "." in fqn:
        head, _, tail = fqn.rpartition(".")
        return head, tail
    return "", fqn


def _join_path(parent: str | None, name: str) -> str:
    """Build the absolute selector for a node, given an optional parent selector."""
    if parent is None:
        return "/" + name
    return parent.rstrip("/") + "/" + name


def _fqn_to_selector(root_path: str, fqn: str) -> str:
    """Map a module fqn (dotted) to a selector path (slash-separated)."""
    if fqn == "":
        return root_path
    return root_path + "/" + fqn.replace(".", "/")


def _diverging_ancestors(a_fqn: str, b_fqn: str) -> tuple[str, str] | None:
    """Find the pair of ancestors where two fqns first diverge.

    Examples:
        ``b1.lin``, ``b1.act``    → ``("b1.lin", "b1.act")`` — siblings under ``b1``
        ``b1.act``, ``b2.lin``    → ``("b1", "b2")``         — diverge at top level
        ``b1``, ``b1.lin``        → ``None``                 — one is ancestor of the other
        ``x``, ``x``              → ``None``                 — self-loop
    """
    if a_fqn == b_fqn:
        return None
    a_parts = a_fqn.split(".") if a_fqn else []
    b_parts = b_fqn.split(".") if b_fqn else []
    i = 0
    while i < min(len(a_parts), len(b_parts)) and a_parts[i] == b_parts[i]:
        i += 1
    if i == len(a_parts) or i == len(b_parts):
        # One is a prefix of the other (ancestor-descendant). Skip; v1 does
        # not emit cross-level edges.
        return None
    return ".".join(a_parts[: i + 1]), ".".join(b_parts[: i + 1])


def _commit_one_node(
    layout: ProjectLayout,
    op: CreateNodeOp,
    *,
    actor: str,
    note: str,
) -> str:
    receipt = apply_patch(
        layout,
        PatchIntent(
            ops=[op],
            actor=actor,
            base_graph_version=layout.load_manifest().graph_version,
            note=note,
        ),
    )
    return receipt.nodes[0]


def _commit_io_ports(layout: ProjectLayout, node_selector: str, *, actor: str) -> None:
    """Create one ``in`` and one ``out`` port on the given (already-saved) node."""
    apply_patch(
        layout,
        PatchIntent(
            ops=[
                CreatePortOp(
                    node=node_selector, name="in", direction="in", port_type="tensor",
                ),
                CreatePortOp(
                    node=node_selector, name="out", direction="out", port_type="tensor",
                ),
            ],
            actor=actor,
            base_graph_version=layout.load_manifest().graph_version,
            note=f"import_model: io ports on {node_selector}",
        ),
    )


def _collect_leaf_edges(
    model: Any, example_inputs: tuple[Any, ...],
) -> set[tuple[str, str]]:
    """Run model under forward hooks + ``TorchDispatchMode``; return leaf
    ``(src_fqn, tgt_fqn)`` data-flow edges.

    The producer map is keyed by ``id(tensor)``. CPython recycles memory
    addresses immediately after GC, so intermediate aten outputs that go out
    of scope would leave stale entries behind and a new tensor at the reused
    address would inherit them. Every stamp therefore registers a
    ``weakref.finalize`` that removes the entry the moment the tensor is
    collected.
    """
    import weakref

    import torch
    from torch.utils._python_dispatch import TorchDispatchMode

    producer: dict[int, set[str]] = {}
    edges: set[tuple[str, str]] = set()

    def _drop(tid: int) -> None:
        producer.pop(tid, None)

    def _stamp(t: torch.Tensor, srcs: set[str]) -> None:
        if not srcs:
            return
        tid = id(t)
        producer[tid] = set(srcs)
        weakref.finalize(t, _drop, tid)

    def _emit_for(t: torch.Tensor, fqn: str) -> None:
        srcs = producer.get(id(t))
        if not srcs:
            return
        for src in srcs:
            if src and src != fqn:
                edges.add((src, fqn))

    def make_pre_hook(fqn: str) -> Callable[..., None]:
        def pre_hook(module: Any, args: Any, kwargs: Any) -> None:
            for t in _iter_tensors(args):
                _emit_for(t, fqn)
            for t in _iter_tensors(kwargs):
                _emit_for(t, fqn)
        return pre_hook

    def make_post_hook(fqn: str) -> Callable[..., None]:
        def post_hook(module: Any, args: Any, output: Any) -> None:
            for t in _iter_tensors(output):
                _stamp(t, {fqn})
        return post_hook

    class _LineageMode(TorchDispatchMode):
        def __init__(self) -> None:
            super().__init__()  # type: ignore[no-untyped-call]

        def __torch_dispatch__(
            self,
            func: Any,
            types: Any,
            args: Any = (),
            kwargs: Any = None,
        ) -> Any:
            kwargs = kwargs or {}
            merged: set[str] = set()
            for t in _iter_tensors(args):
                s = producer.get(id(t))
                if s:
                    merged |= s
            for t in _iter_tensors(kwargs):
                s = producer.get(id(t))
                if s:
                    merged |= s
            out = func(*args, **kwargs)
            if merged:
                for t in _iter_tensors(out):
                    _stamp(t, merged)
            return out

    handles = []
    try:
        for fqn, mod in model.named_modules():
            if fqn == "":
                continue
            handles.append(
                mod.register_forward_pre_hook(make_pre_hook(fqn), with_kwargs=True),
            )
            handles.append(mod.register_forward_hook(make_post_hook(fqn)))

        with torch.no_grad(), _LineageMode():
            model(*example_inputs)
    finally:
        for h in handles:
            h.remove()

    return edges


def _iter_tensors(obj: Any) -> Iterator[torch.Tensor]:
    import torch

    if isinstance(obj, torch.Tensor):
        yield obj
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            yield from _iter_tensors(x)
    elif isinstance(obj, dict):
        for x in obj.values():
            yield from _iter_tensors(x)
