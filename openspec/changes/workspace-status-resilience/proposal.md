# Workspace status resilience

## Why

The user requested a polished, usable frontend and a stable, complete backend. The accepted product remains a quiet canvas-first graph workspace, not a marketing site or an unrelated dashboard. Integration PR #27 already contains the active Node/Edge/Port authoring work. This follow-up builds on its exact head `5f1a037e93a64d138af34615475ee67741d8cf24`; it does not overwrite or merge the existing development branches.

Issue #20 identifies a reproducible presentation bug: `positionSaveError ?? status` permanently masks subsequent primary status/errors after a UI-sidecar save failure.

## Bounded change

- Separate position-save warnings from primary status, with an explicit dismiss action. A successfully committed Node must remain intact.
- Improve TopBar hierarchy, responsive layout, accessible navigation, connection status, and focus/reduced-motion treatment while retaining existing callbacks and the canvas-first layout.
- Harden graph SSE client frame validation and lifecycle cleanup without changing the server event contract or automatically replaying graph writes.
- Establish reproducible frontend/backend/browser acceptance and retain build/test evidence.

## Non-goals

No schema/kernel/Registry/write-authority changes, no Port geometry rewrite, no automatic Agent actions, no production deployment, and no assertion that existing manual acceptance tasks have passed. Cross-process recovery and the other backend issues remain separate design work.

## Verification and delivery

Run existing frontend tests, Svelte/TypeScript checks and build; add focused regression tests; exercise browser behavior against an isolated test project where the environment permits. Preserve exact logs and distinguish new executed checks from inherited CI results. Ship a Draft PR targeting `integration/object-authoring-parity` until all required acceptance is supported by evidence.

The current execution environment has no working outbound DNS or installed GitNexus. GitNexus checks must be explicitly recorded as not run; source-level impact review is not represented as equivalent. No frozen backend symbols will be modified in this follow-up.
