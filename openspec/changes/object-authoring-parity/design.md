# Design: Object Authoring Parity

## Interaction model

The object-level grammar stays stable and small:

- Node: `Ask / Trace / Inspect`
- Edge: `Ask / Inspect`
- Port: `Ask / Inspect`

`Inspect` is the gateway to details plus low-frequency authoring actions. Rename/Edit/Delete must not become additional permanent object-level buttons.

## Node authoring

Node already has server-resolved `node.rename` / `node.delete` affordances and kernel-backed endpoints. This change improves discoverability and consistency:

- Inspect exposes a small Structure/Actions section containing enabled server affordances such as Rename and Delete.
- Right-click continues to expose the same actions.
- Delete / Backspace on selected Node(s) routes through the same server affordance and kernel path; canvas-only deletion remains forbidden.
- Disabled actions show the server-provided reason.
- If a delete removes additional semantic objects, the UI must show the consequence before committing rather than silently hiding it.

## Edge authoring

Review semantics and topology semantics are distinct:

- `Keep / Dismiss / Needs attention` remain review-layer actions.
- `Disconnect` (product wording) is the topology action that deletes the persisted Edge.
- Disconnect is shown in Inspect / structural actions only when the server exposes the corresponding affordance.
- Structural edges such as `contains` are not made directly editable merely for parity.
- Physically disconnecting a LiteGraph data-flow connection and pressing explicit Disconnect must converge on the same kernel delete path.

## Port authoring

Port becomes first-class authored state.

### Create

An eligible Node may expose `port.create`. The Node Inspect Interface section provides Add input / Add output entry points when enabled.

### Update

A Port may expose `port.update`. The initial slice supports:

- `name`
- `port_type`
- `direction` (`in` / `out`) only when the Port has no incident Edge
- a bounded set of presentation/runtime attrs permitted by the server/Registry (initially label, shape, confidence when present/allowed)

The UI must not offer arbitrary raw JSON mutation.

Connected Port edits that can change connection validity (direction or type) are blocked in the initial slice with a deterministic reason. The user disconnects first, then edits. This avoids implicit destructive cascades.

### Delete

A Port may expose `port.delete`. Initial policy: an incident Edge disables deletion with a reason; no silent cascade. Deleting an unconnected Port is one kernel transaction.

## Kernel / API contract

Known object-authoring operations use explicit kernel operations and explicit server executors/endpoints rather than a fake generic action executor.

Expected semantic operations:

- existing `RenameNodeOp`, `DeleteNodeOp`, `DeleteEdgeOp`
- existing `CreatePortOp`
- new Port update operation (single validated semantic op; exact class name may be `UpdatePortOp`)
- new Port delete operation (`DeletePortOp` or equivalent)

### Frozen HTTP contract

Node and Edge retain their existing endpoints:

- `POST /node/{node_id}/rename`
- `DELETE /node/{node_id}`
- `DELETE /edge/{edge_id}`

Port authoring uses these explicit endpoints:

- `POST /node/{node_id}/ports`
  - request: `{ name: string, direction: "in" | "out", port_type?: string, attrs?: object }`
  - response: `{ port_id: string, graph_version: number }`
- `POST /port/{port_id}/update`
  - request: any subset of `{ name, direction, port_type, attrs }`
  - response: `{ port_id: string, graph_version: number }`
- `DELETE /port/{port_id}`
  - response: `{ deleted: string[], graph_version: number }`

`attrs` is a bounded merge/replace surface defined by the server/Registry implementation; it is not permission for arbitrary raw entity JSON editing.

Every endpoint must re-resolve current server affordances and rely on kernel validation. Frontend affordance state is advisory, never authority.

## Registry actions

Registry/action resolver should expose explicit known actions such as:

- `node.rename`
- `node.delete`
- `edge.delete` (product label `Disconnect`)
- `port.create` on Node targets
- `port.update`
- `port.delete`
- existing `context.attach`

Action availability may depend on live graph state. In particular, connected Ports may return disabled `port.update`/`port.delete` with deterministic reasons.

## Frontend architecture

Avoid adding more orchestration to `App.svelte` where possible.

- Keep Port API calls in a focused object-authoring client/module so backend contract changes stay localized.
- Port editing should live in a dedicated small component or isolated NodeInspector section.
- EdgeMenu remains responsible for Edge-specific review presentation but should expose structural Disconnect separately from review actions.
- NodeInspector should project Node structural actions from affordances rather than hard-code domain type rules.

## Safety / consistency invariants

- All real Ports remain independently visible at every zoom.
- No object is removed only from the canvas; semantic delete always goes through the kernel.
- `Dismiss` never means `Delete edge`.
- Port type/direction changes never silently invalidate or remove existing Edges.
- UI never derives write authority from object type strings.
- Unknown server actions are not shown as fake executable menu items.
