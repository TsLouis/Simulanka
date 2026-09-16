# Change: object-authoring-parity

## Why

Frontend v2 now has a stable graph-native interaction grammar, but authoring parity is incomplete. Node deletion/rename exist but are not sufficiently discoverable, Edge review actions are conflated with topology deletion, and Port is inspectable but not authorable. This makes Node / Edge / Port feel inconsistent even though all three are first-class graph objects.

The next slice should complete object authoring without changing the established `Ask / Trace / Inspect` grammar or introducing a generic action framework that the backend cannot execute.

## Goals

- Preserve the stable object grammar:
  - Node: `Ask / Trace / Inspect`
  - Edge: `Ask / Inspect` plus a separate review layer
  - Port: `Ask / Inspect`
- Put low-frequency edit/destructive actions inside Inspect and contextual menus instead of adding another always-visible top-level action.
- Make Node rename/delete discoverable and server-authoritative.
- Make Edge topology deletion explicit and distinct from review semantics.
- Make Port a first-class authored object: create, rename, edit safe fields, and delete.
- Keep all writes behind Registry affordances and kernel validation.
- Preserve LiteGraph native Port geometry and the invariant that every real Port remains independently visible.

## Non-goals

- Generic `/actions/execute`.
- Arbitrary raw JSON editing of Node / Edge / Port entities.
- Agent auto-apply, Undo, or provider-neutral projection transport.
- Replacing LiteGraph connection or Port rendering.
- Bulk graph refactors or domain-specific editing UI.

## Dependency

This change is stacked on the current Frontend v2 + Add Node correctness baseline (`codex/add-node-atomic-creation`) so it inherits the Registry-v1 write compatibility fix and Node+Ports atomic creation contract.
