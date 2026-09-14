## Context

Canvas Add Node currently spans three writes: one kernel patch for the Node, a second kernel patch for template Ports, and a later UI-position write from the frontend. The kernel already supports intent-local Node refs (`CreateNodeOp.ref`, selected later as `@ref`) for atomic multi-entity patches, but `CreatePortOp` still resolves its Node only from committed storage.

Positions are intentionally UI sidecar state and must remain outside the semantic graph.

## Decisions

### 1. Reuse PatchIntent local refs for Ports

`CreatePortOp.node` SHALL accept the same Node selector semantics needed for this use case: when the selector starts with `@`, resolve it from `pending.refs`; otherwise use the existing committed-node resolver. No new temporary-id syntax is introduced.

Validation SHALL see earlier pending Nodes and Ports in the same PatchIntent. Canonical events continue to record real generated entity ids, never the local ref token.

### 2. POST /node is one graph transaction

The server SHALL build one operation list:

1. `CreateNodeOp(..., ref=<request-local handle>)`
2. zero or more `CreatePortOp(node=@<handle>, ...)`

and call `apply_patch_now()` once.

If any Node or Port validation fails, `apply_patch` raises before saving pending entities, so no partial Node/Port is visible and graph_version does not advance.

Duplicate sibling naming remains a server concern and is resolved before building the patch exactly as today.

### 3. Initial position remains UI state

The semantic Node SHALL NOT receive x/y attrs. The frontend already owns per-view position buckets.

During one Add Node request, the frontend SHALL treat the creation-triggered SSE commit as deferred work. Once the response yields the real Node id, it SHALL:

1. write the summon point into the in-memory position bucket immediately;
2. persist that exact delta to `/ui/positions/{rootKey}` and await the result;
3. then release/coalesce any deferred graph reload.

This ensures the first post-create graph rebuild uses the requested position rather than dagre fallback.

A position-persistence failure SHALL be surfaced as a UI error while retaining the correct in-memory position for the current session; it must not roll back the already-valid semantic graph transaction.

### 4. Do not generalize beyond the bug

This change does not create a generic transaction API, generic action executor, client-generated graph ids, or graph/UI-state cross-transaction. It only closes the observable Add Node correctness gap using existing graph and UI-state seams.

## Risks / Trade-offs

- A deferred SSE reload must not suppress unrelated commits permanently. Use a small in-flight/deferred flag/counter and schedule one reload when creation settles.
- Multiple quick Add Node operations may overlap. The guard must support more than one in-flight create rather than a single fragile boolean.
- UI position persistence remains a separate sidecar write by design; graph atomicity applies to Node + Ports, while first-render ordering is enforced by the frontend.
