## 1. Kernel atomicity

- [x] 1.1 Allow `CreatePortOp.node` to resolve an earlier `CreateNodeOp(ref=...)` through the existing PatchIntent-local `@ref` map.
- [x] 1.2 Add kernel coverage proving Node + multiple Ports commit together and a later invalid Port leaves no pending entity persisted / no graph-version advance.

## 2. Server Add Node

- [x] 2.1 Refactor `POST /node` to build one `apply_patch_now()` call containing the Node and all template Ports.
- [x] 2.2 Preserve duplicate sibling suffixing, Registry/action validation, response shape (`node_id`, `name`, `port_ids`, `graph_version`) and one commit event.
- [x] 2.3 Add server regression coverage for atomic failure and one-commit success.

## 3. Initial position handoff

- [x] 3.1 Guard creation-triggered SSE reloads while one or more Add Node requests are in flight.
- [x] 3.2 On create success, write the summon point into the current in-memory position bucket, await persistence of that exact node-id delta, then release one coalesced deferred reload.
- [x] 3.3 Surface position persistence failure without deleting the valid graph entity; keep the correct in-memory position for the current session.
- [x] 3.4 Add focused frontend coverage for deferred reload / overlapping create bookkeeping if extracted into a testable helper.

## 4. Verification

- [x] 4.1 Run targeted kernel/server tests for PatchIntent refs and `POST /node`.
- [x] 4.2 Run frontend `npm test`, `npm run check`, and `npm run build`.
- [ ] 4.3 Manually add several nodes quickly at different summon points and confirm no auto-layout flash, duplicate-name regression, or partial nodes.
- [ ] 4.4 Close #17 only after both graph atomicity and first-render position ordering are verified.

Verification checkpoint:
- Existing backend TDD tests reproduced 4 failures before implementation and pass unchanged afterward. Targeted backend regression suites: 84 passed.
- Frontend: 32 tests passed; Svelte/TypeScript check and production build passed. Changed Python modules pass ruff and mypy strict.
- Supplemental local DOM harness exercised the compiled App script with controlled API responses and a mocked canvas renderer: overlapping/out-of-order creates, queued/in-flight reloads, navigation, failed position persistence, and failed creation all passed. This verifies handoff ordering, not actual canvas rendering.
- Manual canvas QA remains pending: the available browser blocked the local app URL with `ERR_BLOCKED_BY_CLIENT`. Keep PR #19 Draft and #17 open until 4.3 is verified.
