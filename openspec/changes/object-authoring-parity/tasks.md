# Tasks: Object Authoring Parity

## 1. Contract / Registry

- [x] 1.1 Add explicit Registry actions for Edge topology delete and Port create/update/delete.
- [x] 1.2 Define live-state policies for connected Port update/delete and disabled reasons.
- [x] 1.3 Keep existing Node rename/delete affordances unchanged except for presentation/discoverability.

## 2. Kernel + server (backend lane)

- [x] 2.1 Add validated Port update operation covering name, type, safe direction change, and bounded attrs.
- [x] 2.2 Add validated Port delete operation; initial policy rejects Ports with incident Edges.
- [x] 2.3 Reuse existing CreatePortOp for explicit Port creation on an eligible Node.
- [x] 2.4 Expose explicit Port create/update/delete endpoints that revalidate current affordances.
- [x] 2.5 Project existing `DELETE /edge/{id}` as `edge.delete` / product `Disconnect` affordance.
- [x] 2.6 Add backend tests for happy paths, connected-Port rejection, stale/invalid refs, Registry authority, and graph-version atomicity.

## 3. Frontend authoring UX (frontend lane)

- [x] 3.1 Node Inspect exposes Rename/Delete from server affordances; right-click and Delete/Backspace converge on same path.
- [x] 3.2 Edge Inspect exposes explicit `Disconnect`, visually separated from review actions.
- [x] 3.3 Node Inspect Interface exposes Add input / Add output when `port.create` is enabled.
- [x] 3.4 Port Inspect exposes an Edit surface for name/type/safe direction/allowed attrs when `port.update` is enabled.
- [x] 3.5 Port Inspect exposes Delete when `port.delete` is enabled; disabled reason is visible when connected.
- [ ] 3.6 Preserve native LiteGraph Port geometry and independent Port visibility after edits/reloads.
- [x] 3.7 Add frontend tests for action projection, disabled reasons, form validation, and connected-Port topology locking. Reload/persistence coverage is verified in integration tests 4.3–4.5.

## 4. Integration

- [x] 4.1 Merge/rebase backend lane into the integration branch without changing the frozen interaction grammar.
- [x] 4.2 Wire frontend client calls to final backend contract.
- [x] 4.3 Verify create/edit/delete Port persists across graph reload and SSE affected refs include the owning Node. Canvas geometry remains under 3.6 / manual acceptance.
- [x] 4.4 Verify Edge Disconnect and physical wire removal converge on the same persisted `DELETE /edge/{id}` path and reload result.
- [x] 4.5 Verify Node delete persists across reload and never leaves a server-side phantom object.

## 5. Manual acceptance

- [ ] 5.1 Add an input and output Port to an eligible Node, rename them, edit type/direction while unconnected, reload, and verify persistence.
- [ ] 5.2 Connect Ports, verify unsafe direction/type/delete changes become unavailable with deterministic reasons, disconnect, then edit successfully.
- [ ] 5.3 Explicitly Disconnect an Edge and confirm this is distinct from Dismiss/Needs attention.
- [ ] 5.4 Rename/Delete a Node from Inspect and from keyboard/context menu; verify identical server-authoritative behavior.
- [ ] 5.5 Stress add/edit/delete/connect/disconnect with SSE enabled and confirm no duplicate, phantom, or stale objects.
