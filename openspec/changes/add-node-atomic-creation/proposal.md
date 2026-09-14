## Why

Issue #17 exposes two correctness gaps in Canvas Add Node: Node and template Ports are currently committed in separate graph patches, and the initial canvas position is persisted only after the create response. A Port validation failure can therefore leave a partial Node, while SSE can rebuild the graph before the requested summon-point position is known locally.

The user-visible operation is one action: choose a template at a canvas point and create one concrete Node there. The implementation SHOULD preserve that atomic mental model without moving UI layout state into the semantic graph.

## What Changes

- Extend the existing PatchIntent local-ref mechanism so `CreatePortOp.node` can reference an earlier `CreateNodeOp(ref=...)` in the same patch.
- Make `POST /node` create the Node and all requested template Ports in one authoritative kernel patch. Any validation failure leaves no Node or Port behind.
- Preserve duplicate sibling name suffixing and current Registry/action validation.
- Coordinate the frontend Add Node request with SSE reloads so the new Node's summon-point position enters the local position cache and is persisted before the creation-triggered reload may render it.
- Keep positions in `.simulanka/ui/positions.json`; do not add presentation coordinates to Node attrs or the graph schema.

## Impact

- Kernel: a narrow selector-resolution extension for `CreatePortOp` using the already-existing intent-local `@ref` concept.
- Server: `POST /node` emits one graph commit for Node + Ports instead of two.
- Frontend: Add Node temporarily defers the relevant SSE reload until initial position handoff is complete.
- No change to write authority, Registry policy, graph entity schema, template semantics, or Agent behavior.
