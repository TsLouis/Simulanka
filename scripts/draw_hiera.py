"""One-off renderer: print a multi-level structure diagram of Hiera.

Reads the model via the same build_fn the importer uses, collects data_flow
edges with forward hooks, then prints three views:

  L0 — root view (top-level children + flows between them)
  L1 — stage view (blocks grouped by pool boundaries)
  L2 — block detail (one regular block + one pool block, expanded)

Not part of Simulanka; meant for human inspection of import output.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import Any

sys.path.insert(0, "/home/ts/mnt/remote/tot/baselines/DS_r")

from simulanka.importer.torch_export import _collect_leaf_edges  # noqa: E402
from simulanka_builds.ds_r import build_hiera  # noqa: E402


def _rollup_at_depth(
    leaf_edges: set[tuple[str, str]], depth: int,
) -> set[tuple[str, str]]:
    """Collapse every fqn to its first `depth` dotted components, drop self-loops."""
    def head(fqn: str) -> str:
        parts = fqn.split(".")
        return ".".join(parts[: depth + 1])

    out: set[tuple[str, str]] = set()
    for a, b in leaf_edges:
        ha, hb = head(a), head(b)
        if ha != hb:
            out.add((ha, hb))
    return out


def _filter_subtree(
    leaf_edges: set[tuple[str, str]], prefix: str,
) -> set[tuple[str, str]]:
    """Edges where both endpoints live under `prefix`."""
    return {
        (a, b)
        for a, b in leaf_edges
        if (a == prefix or a.startswith(prefix + "."))
        and (b == prefix or b.startswith(prefix + "."))
    }


def main() -> None:
    model, inputs = build_hiera()
    named = list(model.named_modules())
    by_fqn: dict[str, Any] = {fqn: mod for fqn, mod in named}

    print("Collecting forward-hook trace ...", file=sys.stderr)
    leaf = _collect_leaf_edges(model, inputs)
    print(f"  {len(leaf)} leaf edges captured", file=sys.stderr)

    # ---- detect stage boundaries (pool blocks) ----
    pool_indices = []
    for fqn, mod in named:
        if fqn.startswith("blocks.") and fqn.count(".") == 1:
            attn = getattr(mod, "attn", None)
            if attn is not None and getattr(attn, "q_pool", None) is not None:
                pool_indices.append(int(fqn.split(".")[1]))
    num_blocks = sum(
        1 for f, _ in named if f.startswith("blocks.") and f.count(".") == 1
    )

    # stages: [0, p1), [p1, p2), [p2, p3), [p3, num_blocks)
    bounds = [0, *pool_indices, num_blocks]
    stages = list(zip(bounds[:-1], bounds[1:], strict=False))

    # =================================================================
    # L0 — root view
    # =================================================================
    print("\n" + "=" * 70)
    print("L0  Hiera (root)")
    print("=" * 70)
    top_children = sorted(
        f for f, _ in named if f and "." not in f
    )
    for c in top_children:
        mod = by_fqn[c]
        cls = type(mod).__name__
        n_params = sum(p.numel() for p in mod.parameters())
        extra = ""
        if cls == "ModuleList":
            extra = f"  [{len(mod)} blocks, {len(stages)} stages]"
        print(f"  {c:18s}  {cls:14s}  params={n_params:>12,}{extra}")

    # Edges between top-level children
    top_edges = _rollup_at_depth(leaf, depth=0)
    print("\n  data_flow at root:")
    for s, t in sorted(top_edges):
        print(f"    {s}  →  {t}")

    # =================================================================
    # L1 — stage view: blocks grouped by pool boundary, edges between stages
    # =================================================================
    print("\n" + "=" * 70)
    print("L1  Stages inside `blocks` (pool blocks mark stage transitions)")
    print("=" * 70)

    # map block fqn → stage id
    stage_of: dict[int, int] = {}
    for sid, (lo, hi) in enumerate(stages):
        for i in range(lo, hi):
            stage_of[i] = sid

    # within-blocks edges only — collapse every leaf fqn to its top-level
    # block index (blocks.N.* → N), drop intra-block self-loops, count distinct
    # block→block edges per stage and stage→stage.
    block_edges = _filter_subtree(leaf, "blocks")
    block_pairs: set[tuple[int, int]] = set()
    for a, b in block_edges:
        ai = int(a.split(".")[1])
        bi = int(b.split(".")[1])
        if ai != bi:
            block_pairs.add((ai, bi))

    inter_stage: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)
    intra_stage: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for ai, bi in block_pairs:
        sa, sb = stage_of[ai], stage_of[bi]
        if sa != sb:
            inter_stage[(sa, sb)].add((ai, bi))
        else:
            intra_stage[sa].add((ai, bi))

    for sid, (lo, hi) in enumerate(stages):
        marker = "(pool start)" if sid > 0 else "(stem-fed)"
        print(
            f"  stage {sid}: blocks.{lo}..blocks.{hi - 1}  "
            f"[{hi - lo} blocks]  {marker}"
        )
        print(
            f"      intra-stage block→block edges: {len(intra_stage[sid])}  "
            f"(of {(hi - lo) * (hi - lo - 1)} possible)",
        )

    print("\n  inter-stage flow (distinct block→block edges):")
    for (s, t), pairs in sorted(inter_stage.items()):
        arrow = "→" if t == s + 1 else "⇢"
        print(f"    stage {s}  {arrow}  stage {t}    ({len(pairs)} edges)")

    # =================================================================
    # L2 — block detail
    # =================================================================
    for label, idx in [("regular block", 0), ("pool block (stage transition)", 5)]:
        print("\n" + "=" * 70)
        print(f"L2  blocks.{idx}  —  {label}  ({type(by_fqn[f'blocks.{idx}']).__name__})")
        print("=" * 70)
        prefix = f"blocks.{idx}"
        sub_children = sorted(
            (f for f, _ in named
             if f.startswith(prefix + ".") and f.count(".") == 2)
        )
        for c in sub_children:
            cls = type(by_fqn[c]).__name__
            n_params = sum(p.numel() for p in by_fqn[c].parameters())
            print(f"  {c.split('.')[-1]:14s}  {cls:18s}  params={n_params:>10,}")

        # internal data flow at depth=2 (children of blocks.N)
        sub_edges = _filter_subtree(leaf, prefix)
        rolled: set[tuple[str, str]] = set()
        for a, b in sub_edges:
            a_parts = a.split(".")
            b_parts = b.split(".")
            # roll up to direct child of blocks.N
            if len(a_parts) < 3 or len(b_parts) < 3:
                continue
            a_head = ".".join(a_parts[:3])
            b_head = ".".join(b_parts[:3])
            if a_head != b_head:
                rolled.add((a_head.replace(prefix + ".", ""),
                            b_head.replace(prefix + ".", "")))

        print(f"\n  internal data_flow ({len(rolled)} peer edges):")
        for s, t in sorted(rolled):
            print(f"    {s}  →  {t}")


if __name__ == "__main__":
    main()
