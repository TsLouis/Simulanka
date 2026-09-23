## ADDED Requirements

### Requirement: Independent recoverable feedback
The workspace SHALL display primary operation status independently from layout-persistence warnings and SHALL retain successfully committed graph entities when a layout write fails.

#### Scenario: A new error follows a layout failure
- **WHEN** a Node is committed, its position save fails, and a later graph read fails
- **THEN** the layout warning and new primary error are both available
- **AND** dismissing the warning neither hides the primary error nor deletes the Node

### Requirement: Current-view read ownership
Only the newest read for the active view SHALL update graph presentation or primary read-error status; disposal SHALL invalidate pending reads.

#### Scenario: A superseded read finishes late
- **WHEN** an earlier request resolves or rejects after a newer request or navigation
- **THEN** the older result does not replace current graph presentation or error status

### Requirement: Safe event recovery
The client SHALL validate graph event shapes and SHALL refresh the active graph after each valid ready handshake without replaying semantic writes.

#### Scenario: A graph commit was missed while disconnected
- **WHEN** the event stream reconnects with ready after an offline commit
- **THEN** the active graph is refreshed through the existing creation/reload gate

#### Scenario: A malformed frame or closed subscription receives data
- **WHEN** a malformed frame arrives
- **THEN** no malformed payload reaches graph consumers and a later valid frame remains deliverable
- **WHEN** the subscription is closed
- **THEN** handlers are detached and queued callbacks cannot update the workspace

### Requirement: Accessible responsive navigation
The toolbar SHALL expose named history controls, current graph location, textual connection status, visible keyboard focus, and independent readable warnings at desktop and narrow viewport sizes.

#### Scenario: The toolbar wraps or opens a warning
- **WHEN** viewport width or toolbar content changes
- **THEN** navigation remains available without page-level horizontal overflow and the canvas backing dimensions follow its rendered dimensions

### Requirement: Search visible object types
The add-node menu SHALL match the visible server-supplied type as well as label, name and category, without adding otherwise unavailable catalog entries.

#### Scenario: A template name differs from its type
- **WHEN** the user searches `directory` and the available template is named `dir` with type `directory`
- **THEN** the template remains discoverable and can be created through the existing server-authorized path

### Requirement: Port transport parity
Development-mode Port update and delete requests SHALL reach the configured API with their method, path and body intact.

#### Scenario: Editing a Port through the development server
- **WHEN** the client sends a Port update or delete through Vite
- **THEN** the existing backend endpoint receives the request instead of the SPA fallback
