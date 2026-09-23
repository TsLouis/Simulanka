## 1. Implementation
- [x] 1.1 Inspect integrated source and record bounded impact/non-goals.
- [x] 1.2 Separate primary status and dismissible position warnings.
- [x] 1.3 Improve TopBar responsive navigation, focus and status hierarchy.
- [x] 1.4 Validate event frames and clean up subscriptions.
- [x] 1.5 Guard stale view reads and schedule reconnect catch-up.
- [x] 1.6 Track canvas resizing and disposal of scheduled reads.

- [x] 1.7 Make visible object types searchable (browser-discovered gap).

## 2. Verification
- [x] 2.1 Run 14 focused event/request-gate/template-search tests locally.
- [x] 2.2 Run full frontend tests, Svelte/TypeScript check and production build on proposed code.
- [x] 2.3 Run full backend regression on proposed code.
- [ ] 2.4 Run real-browser warning, reconnect, navigation and viewport checks; inspect screenshots.
- [ ] 2.5 Final diff review and publish exact verification evidence.
- [ ] 2.6 GitNexus and OpenSpec CLI gates in a fully provisioned project environment.

## 3. Acceptance boundary
Full manual Port/Edge geometry, Agent interaction and existing real-project acceptance remain outside this follow-up. No production deployment, main merge, existing issue closure or spec archive is authorized by automated smoke alone.

Executed on be582d9: 57 frontend tests, zero Svelte diagnostics, production build; backend 397 passed / 6 skipped. First browser run exposed type-search mismatch before warning/reconnect scenarios; those remain pending the next pass.
