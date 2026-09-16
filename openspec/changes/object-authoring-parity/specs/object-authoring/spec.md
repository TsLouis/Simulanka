# Object Authoring Requirements

## Requirement: stable object grammar

The frontend SHALL preserve the established object-level grammar while authoring capabilities expand.

### Scenario: Node selected
- WHEN a Node is selected
- THEN the primary contextual actions remain `Ask / Trace / Inspect`
- AND Rename/Delete are available through Inspect/contextual authoring surfaces when server affordances allow them.

### Scenario: Edge selected
- WHEN an Edge is selected
- THEN the primary contextual actions remain `Ask / Inspect`
- AND review actions remain separate from topology actions.

### Scenario: Port inspected
- WHEN a Port is inspected
- THEN `Ask / Inspect` remain the object-level actions
- AND editing is entered from the Inspect surface rather than adding a permanent top-level Edit button.

## Requirement: server-authoritative Node deletion

Node deletion SHALL never be canvas-only.

### Scenario: keyboard deletion
- WHEN the user presses Delete or Backspace on selected semantic Nodes
- THEN the frontend SHALL resolve/use the server `node.delete` affordance
- AND SHALL persist deletion through the kernel
- AND SHALL NOT remove semantic Nodes only from the LiteGraph canvas.

### Scenario: deletion unavailable
- WHEN server policy disables `node.delete`
- THEN the frontend SHALL leave the Node unchanged
- AND SHALL surface the deterministic server reason.

## Requirement: Edge topology deletion is distinct from review

The product SHALL distinguish removing an Edge from reviewing an Edge.

### Scenario: Disconnect
- WHEN the server exposes `edge.delete` for a persisted Edge
- THEN Inspect SHALL offer product action `Disconnect`
- AND executing it SHALL use the same persisted delete path as physical connection removal.

### Scenario: Dismiss
- WHEN the user chooses Dismiss / Looks wrong on a reviewable Edge
- THEN the system SHALL apply review semantics only
- AND SHALL NOT interpret Dismiss as topology deletion.

## Requirement: Port creation

Eligible Nodes SHALL support explicit Port creation through server authority.

### Scenario: add input or output
- WHEN a Node exposes enabled `port.create`
- THEN its Interface Inspect surface SHALL offer Add input / Add output
- AND the created Port SHALL be persisted through the kernel
- AND SHALL appear as its own native LiteGraph Port handle after graph reload.

## Requirement: Port update

A Port SHALL support bounded semantic editing when server policy allows it.

### Scenario: unconnected Port edit
- GIVEN a Port with no incident Edge
- WHEN `port.update` is enabled
- THEN the user MAY update name, port type, safe direction, and server-permitted attrs
- AND the update SHALL be one validated semantic transaction.

### Scenario: connected Port topology-sensitive edit
- GIVEN a Port with one or more incident Edges
- WHEN the user attempts to change direction, type, or another field that can invalidate connection eligibility
- THEN the server SHALL disable/reject that edit with a deterministic reason
- AND the frontend SHALL NOT silently delete or rewrite incident Edges.

### Scenario: arbitrary attrs
- WHEN a Port contains raw attrs not declared as editable
- THEN the frontend SHALL render them read-only
- AND SHALL NOT expose a generic raw JSON editor.

## Requirement: Port deletion

Port deletion SHALL be explicit and safe.

### Scenario: unconnected Port
- GIVEN an unconnected Port
- WHEN `port.delete` is enabled and the user confirms the structural action
- THEN the Port SHALL be deleted through the kernel
- AND no other semantic object SHALL be removed implicitly.

### Scenario: connected Port
- GIVEN a Port with incident Edges
- THEN `port.delete` SHALL be disabled in the initial slice
- AND the disabled reason SHALL tell the user to disconnect incident Edges first.

## Requirement: Port visual invariants

Authoring SHALL preserve the Frontend v2 Port invariants.

### Scenario: any zoom level
- WHEN the graph is rendered at any supported zoom level
- THEN every real Port SHALL remain independently visible and independently positioned
- AND Port labels/details MAY reduce with density
- BUT semantic Port handles SHALL NOT collapse, merge, aggregate, or be replaced by a second custom geometry system.

## Requirement: known executors only

Object authoring SHALL use explicit known execution paths.

### Scenario: action projection
- WHEN the server returns a known authoring affordance
- THEN the frontend MAY project it only if an explicit executor/client path exists
- AND SHALL NOT create a fake generic `/actions/execute` or nonfunctional universal overflow menu.
