## 1. Design and evidence

- [x] 1.1 Review PR #15 against current server/Registry/Session contracts and record the backend mapping, deferred capabilities and pre-implementation Codex review in design.md.
- [x] 1.2 Reproduce duplicate versions on the unchanged baseline with independently gated processes and record the actual outcome.

## 2. Shared write boundary

- [x] 2.1 Add the canonical-root reentrant OS lock; verify threads, processes, nesting, independent projects, failure release, owner death and fork behavior.
- [x] 2.2 Protect explicit and live-version graph commits; verify one winner for the same base, successful fresh retries, continuous events and correct hashes/doctor.
- [x] 2.3 Protect init/import/migrations and checkpoint lifecycle; verify competing maintenance calls and lock exclusion from persisted data.
- [x] 2.4 Keep server/agent state-policy checks and writes in the same boundary; verify stale Keep refusal and HTTP/library interleaving without locking Provider execution.

## 3. Compatibility and delivery

- [x] 3.1 Update docs/kernel.md and send concrete PR #15/backend follow-up notes; verify references and preserve the frontend task's file ownership.
- [x] 3.2 Run ruff, mypy --strict, targeted and full pytest, OpenSpec validation, and GitNexus detect-changes; record baseline/environment failures separately.
- [ ] 3.3 Review the final diff, publish the branch/PR and update #9 with verification evidence; sync/archive only after acceptance gates pass.
- [ ] 3.4 Resolve the remaining full-suite/type-check environment gates documented in verification.md, rerun them successfully, then merge and sync/archive after acceptance.
