## 1. Kernel atomicity

- [ ] 1.1 Allow `CreatePortOp.node` to resolve an earlier `CreateNodeOp(ref=...)` through the existing PatchIntent-local `@ref` map.
- [ ] 1.2 Add kernel coverage proving Node + multiple Ports commit together and a later invalid Port leaves no pending entity persisted / no graph-version advance.

## 2. Server Add Node

- [ ] 2.1 Refactor `POST /node` to build one `apply_patch_now()` call containing the Node and all template Ports.
- [ ] 2.2 Preserve duplicate sibling suffixing, Registry/action validation, response shape (`node_id`, `name`, `port_ids`, `graph_version`) and one commit event.
- [ ] 2.3 Add server regression coverage for atomic failure and one-commit success.

## 3. Initial position handoff

- [ ] 3.1 Guard creation-triggered SSE reloads while one or more Add Node requests are in flight.
- [ ] 3.2 On create success, write the summon point into the current in-memory position bucket, await persistence of that exact node-id delta, then release one coalesced deferred reload.
- [ ] 3.3 Surface position persistence failure without deleting the valid graph entity; keep the correct in-memory position for the current session.
- [ ] 3.4 Add focused frontend coverage for deferred reload / overlapping create bookkeeping if extracted into a testable helper.

## 4. Verification

- [ ] 4.1 Run targeted kernel/server tests for PatchIntent refs and `POST /node`.
- [ ] 4.2 Run frontend `npm test`, `npm run check`, and `npm run build`.
- [ ] 4.3 Manually add several nodes quickly at different summon points and confirm no auto-layout flash, duplicate-name regression, or partial nodes.
- [ ] 4.4 Close #17 only after both graph atomicity and first-render position ordering are verified.
