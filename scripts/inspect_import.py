"""One-shot importer inspector.

Run ``simulanka.importer.import_model`` against any ``pkg.mod:fn`` builder
into a throwaway ProjectLayout and print a top-level structure summary
(submodule count, top-level children, data_flow edges between them).

Useful for sanity-checking that the importer survives a model end-to-end
before wiring it into a real project graph.

    python scripts/inspect_import.py --build simulanka_builds.ds_r:build_hiera
    python scripts/inspect_import.py --build simulanka_builds.ds_r:build_mask_decoder \\
        --syspath /home/ts/mnt/remote/tot/baselines/DS_r
"""

from __future__ import annotations

import argparse
import importlib
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from simulanka.importer import import_model
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import init_project
from simulanka.storage.entity_store import iter_edges, iter_nodes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True, help="pkg.module:function")
    ap.add_argument(
        "--syspath",
        action="append",
        default=[],
        help="Extra dirs to prepend to sys.path before resolving --build "
        "(repeatable).",
    )
    args = ap.parse_args()

    for p in args.syspath:
        sys.path.insert(0, p)

    mod_name, _, fn_name = args.build.partition(":")
    build_fn = getattr(importlib.import_module(mod_name), fn_name)

    with tempfile.TemporaryDirectory() as tmp:
        layout = init_project(Path(tmp), with_scaffold=False).layout
        apply_patch(layout, PatchIntent(
            ops=[CreateNodeOp(type="directory", name="models")],
            actor="inspect", base_graph_version=layout.load_manifest().graph_version,
        ))
        result = import_model(layout, build_fn, name=fn_name, parent="/models")

        nodes_by_id = {n.id: n for n in iter_nodes(layout)}
        edges = [e for e in iter_edges(layout) if e.type == "data_flow"]

    fqn_by_id = {nid: fqn for fqn, nid in result.module_node_ids.items()}
    top_children = sorted(f for f in result.module_node_ids if f and "." not in f)
    children_set = set(top_children)

    print(f"\n{args.build}")
    print(f"  submodules:      {len(result.module_node_ids) - 1}")
    print(f"  data_flow edges: {len(edges)} (peer-rolled)")
    print(f"  top-level children: {len(top_children)}")

    top_pairs: dict[tuple[str, str], int] = defaultdict(int)
    for e in edges:
        a = fqn_by_id.get(e.source_id, "?")
        b = fqn_by_id.get(e.target_id, "?")
        ah = a.split(".", 1)[0]
        bh = b.split(".", 1)[0]
        if ah in children_set and bh in children_set and ah != bh:
            top_pairs[(ah, bh)] += 1

    print("\n  L0 data_flow (top-level child → child, edges in subtree):")
    for (s, t), n in sorted(top_pairs.items()):
        print(f"    {s:30s} → {t:30s}  ({n})")

    print("\n  top-level children:")
    for c in top_children:
        nid = result.module_node_ids[c]
        cls = nodes_by_id[nid].attrs.get("class_name", "?")
        sub = sum(
            1 for f in result.module_node_ids if f == c or f.startswith(c + ".")
        )
        print(f"    {c:30s} {cls:24s}  ({sub} nodes in subtree)")


if __name__ == "__main__":
    main()
