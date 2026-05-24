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
import inspect
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import (
    CreateEdgeOp,
    CreateNodeOp,
    CreatePortOp,
    IntentOp,
    PatchIntent,
)
from simulanka.layout.project import ProjectLayout
from simulanka.registry.types import PortDirection

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


@dataclass(frozen=True)
class _PortSpec:
    """One observed/inferred port slot. ``label`` is the semantic name (param /
    kwarg key / dict key); ``shape`` is set only when the slot is a single
    tensor observed in a forward pass."""

    label: str | None
    shape: list[int] | None = None


@dataclass(frozen=True)
class _ObservedIO:
    """Per-module input/output slots seen in one real forward pass."""

    inputs: list[_PortSpec]
    outputs: list[_PortSpec]


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

    # 1. Forward-pass trace up front. Pure in-memory work — no graph writes
    # yet — yielding both the leaf data-flow edges and the per-module observed
    # IO that the ports below are derived from.
    leaf_edges: set[tuple[str, str]]
    observed_io: dict[str, _ObservedIO]
    if example_inputs is not None:
        try:
            leaf_edges, observed_io = _run_forward_trace(model, example_inputs)
        except Exception as exc:  # noqa: BLE001 — surface forward-pass failures
            raise ImportError(f"forward-hook trace failed: {exc!r}") from exc
    else:
        leaf_edges, observed_io = set(), {}

    # 2. Hierarchy via named_modules().
    named = list(model.named_modules())
    # Build a map fqn → module for attrs.
    by_fqn = {fqn: mod for fqn, mod in named}

    # 3. Commit root model node + its ports.
    root_path = _join_path(parent, name)
    root_class_module, root_source_file = _source_location(type(model))
    root_attrs: dict[str, Any] = {
        "class_name": type(model).__name__,
        "class_module": root_class_module,
        "num_params": _count_params(model),
        "fqn": "",
    }
    if root_source_file is not None:
        root_attrs["source_file"] = root_source_file
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
    _commit_ports(layout, root_path, model, observed_io.get(""), actor=actor)

    fqn_to_id: dict[str, str] = {"": model_id}

    # 4. Commit submodule nodes in BFS order (depth ascending) so parents
    # are already on disk when their children resolve.
    submodule_fqns = sorted(
        (fqn for fqn, _ in named if fqn != ""),
        key=lambda f: (f.count("."), f),
    )
    for fqn in submodule_fqns:
        mod = by_fqn[fqn]
        parent_fqn, leaf = _split_fqn(fqn)
        class_module, source_file = _source_location(type(mod))
        attrs: dict[str, Any] = {
            "class_name": type(mod).__name__,
            "class_module": class_module,
            "num_params": _count_params(mod, recurse=False),
            "fqn": fqn,
        }
        if source_file is not None:
            attrs["source_file"] = source_file
        node_id = _commit_one_node(
            layout,
            CreateNodeOp(
                type="module",
                name=leaf,
                parent=_fqn_to_selector(root_path, parent_fqn),
                attrs=attrs,
            ),
            actor=actor,
            note=f"import_model: {fqn}",
        )
        fqn_to_id[fqn] = node_id
        _commit_ports(
            layout, _fqn_to_selector(root_path, fqn), mod,
            observed_io.get(fqn), actor=actor,
        )

    # 5. Structure-only mode: no forward pass, no data_flow edges.
    if example_inputs is None:
        return ImportResult(
            model_node_id=model_id,
            module_node_ids=fqn_to_id,
            data_flow_edge_ids=[],
        )

    # 6. Roll up leaf edges to diverging-ancestor pairs and dedupe.
    peer_edges: set[tuple[str, str]] = set()
    for src_fqn, tgt_fqn in leaf_edges:
        if src_fqn not in fqn_to_id or tgt_fqn not in fqn_to_id:
            continue
        pair = _diverging_ancestors(src_fqn, tgt_fqn)
        if pair is not None:
            peer_edges.add(pair)

    # 7. Commit data_flow edges, each marked source="trace" — machine-observed,
    # to be distinguished from the user-drawn / agent-verified edges of §13. One
    # patch per edge keeps the event log informative; volume is
    # O(#peer-relations), typically small.
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
                        attrs={"source": "trace"},
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


def _source_location(cls: type) -> tuple[str, str | None]:
    """Where a module class is defined: dotted module path + source file.

    This is the §13.5.3 foundation — the agent reads a node's ``forward`` from
    here to propose ghost edges. Kept as bare locators (not the source text) so
    it stays decoupled from how the agent prompt is built. ``source_file`` is
    ``None`` for C-implemented / builtin modules that have no Python source.
    """
    module = getattr(cls, "__module__", None) or ""
    try:
        source_file = inspect.getsourcefile(cls)
    except (TypeError, OSError):
        source_file = None
    return module, source_file


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


def _commit_ports(
    layout: ProjectLayout,
    node_selector: str,
    module: Any,
    io: _ObservedIO | None,
    *,
    actor: str,
) -> None:
    """Create the in/out ports of one (already-saved) node.

    ``in``/``out`` are always present as the structural primary slots that
    ``data_flow`` edges attach to; extra observed slots become ``in1``/``out1``/…
    Each port's ``attrs["confidence"]`` is the honest tier (§13.3.1):

    * ``verified`` — the slot was seen in the real forward pass (``io`` given).
      ``shape`` is recorded for single-tensor slots; ``label`` for the param /
      kwarg / dict key when it differs from the structural name.
    * ``inferred`` — no forward observation for this module (it was never hit,
      or the import was structure-only). Inputs come from the ``forward``
      signature; the single output slot is a placeholder. No shapes.
    """
    if io is not None:
        in_specs = list(io.inputs)
        out_specs = list(io.outputs)
        confidence = "verified"
    else:
        in_specs = [_PortSpec(label) for label in _signature_input_labels(module)]
        out_specs = []
        confidence = "inferred"

    # Pad so the structural primary ports always exist.
    if not in_specs:
        in_specs = [_PortSpec(None)]
    if not out_specs:
        out_specs = [_PortSpec(None)]

    ops: list[IntentOp] = []
    for i, spec in enumerate(in_specs):
        ops.append(_port_op(node_selector, i, "in", spec, confidence))
    for i, spec in enumerate(out_specs):
        ops.append(_port_op(node_selector, i, "out", spec, confidence))

    apply_patch(
        layout,
        PatchIntent(
            ops=ops,
            actor=actor,
            base_graph_version=layout.load_manifest().graph_version,
            note=f"import_model: ports on {node_selector}",
        ),
    )


def _port_op(
    node_selector: str,
    index: int,
    direction: PortDirection,
    spec: _PortSpec,
    confidence: str,
) -> CreatePortOp:
    """One ``CreatePortOp``. Slot 0 keeps the bare ``in``/``out`` name; later
    slots are suffixed (``in1``, ``out1``, …). Semantics live in ``attrs``."""
    name = direction if index == 0 else f"{direction}{index}"
    attrs: dict[str, Any] = {"confidence": confidence}
    if spec.label and spec.label != name:
        attrs["label"] = spec.label
    if spec.shape is not None:
        attrs["shape"] = spec.shape
    return CreatePortOp(
        node=node_selector,
        name=name,
        direction=direction,
        port_type="tensor",
        attrs=attrs,
    )


def _signature_input_labels(module: Any) -> list[str]:
    """Forward-signature parameter names (minus ``self``, ``*args``, ``**kwargs``).

    Used only on the inferred path, where no real forward pass labelled the
    inputs. Best-effort: a C-implemented or unintrospectable ``forward`` yields
    an empty list and the caller pads a single placeholder ``in`` port.
    """
    try:
        params = list(inspect.signature(type(module).forward).parameters.values())
    except (ValueError, TypeError):
        return []
    skip = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    return [p.name for p in params[1:] if p.kind not in skip]


def _input_specs(module: Any, args: Any, kwargs: Any) -> list[_PortSpec]:
    """Tensor-bearing input slots of one observed call, labelled by the forward
    signature (positional) and kwarg keys."""
    import torch

    try:
        params = list(inspect.signature(type(module).forward).parameters.values())[1:]
    except (ValueError, TypeError):
        params = []
    positional = (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    pos_names = [p.name for p in params if p.kind in positional]

    specs: list[_PortSpec] = []
    for i, a in enumerate(args):
        if not _has_tensor(a):
            continue
        label = pos_names[i] if i < len(pos_names) else None
        shape = list(a.shape) if isinstance(a, torch.Tensor) else None
        specs.append(_PortSpec(label, shape))
    for key, value in kwargs.items():
        if not _has_tensor(value):
            continue
        shape = list(value.shape) if isinstance(value, torch.Tensor) else None
        specs.append(_PortSpec(str(key), shape))
    return specs


def _output_specs(output: Any) -> list[_PortSpec]:
    """Tensor-bearing output slots of one observed call. A bare tensor is one
    unlabelled slot; tuples/lists keep positional order; dict keys become labels."""
    import torch

    if isinstance(output, torch.Tensor):
        return [_PortSpec(None, list(output.shape))]
    if isinstance(output, (tuple, list)):
        specs: list[_PortSpec] = []
        for x in output:
            if not _has_tensor(x):
                continue
            shape = list(x.shape) if isinstance(x, torch.Tensor) else None
            specs.append(_PortSpec(None, shape))
        return specs
    if isinstance(output, dict):
        dict_specs: list[_PortSpec] = []
        for key, value in output.items():
            if not _has_tensor(value):
                continue
            shape = list(value.shape) if isinstance(value, torch.Tensor) else None
            dict_specs.append(_PortSpec(str(key), shape))
        return dict_specs
    return []


def _has_tensor(obj: Any) -> bool:
    for _ in _iter_tensors(obj):
        return True
    return False


def _run_forward_trace(
    model: Any, example_inputs: tuple[Any, ...],
) -> tuple[set[tuple[str, str]], dict[str, _ObservedIO]]:
    """Run *model* once under forward hooks + ``TorchDispatchMode``.

    Returns ``(edges, io)`` where *edges* are leaf ``(src_fqn, tgt_fqn)``
    data-flow relations and *io* maps each fqn ("" for root) to the input/output
    slots **first** observed for that module (a module called more than once
    keeps its first call's arity/shapes).

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
    io_inputs: dict[str, list[_PortSpec]] = {}
    io_outputs: dict[str, list[_PortSpec]] = {}

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
            if fqn not in io_inputs:
                io_inputs[fqn] = _input_specs(module, args, kwargs)
            for t in _iter_tensors(args):
                _emit_for(t, fqn)
            for t in _iter_tensors(kwargs):
                _emit_for(t, fqn)
        return pre_hook

    def make_post_hook(fqn: str) -> Callable[..., None]:
        def post_hook(module: Any, args: Any, output: Any) -> None:
            if fqn not in io_outputs:
                io_outputs[fqn] = _output_specs(output)
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
            output = model(*example_inputs)
    finally:
        for h in handles:
            h.remove()

    # Hooks fire only on submodules; capture the root's IO from the call itself.
    io_inputs[""] = _input_specs(model, example_inputs, {})
    io_outputs[""] = _output_specs(output)

    io = {
        fqn: _ObservedIO(
            inputs=io_inputs.get(fqn, []),
            outputs=io_outputs.get(fqn, []),
        )
        for fqn in set(io_inputs) | set(io_outputs)
    }
    return edges, io


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
