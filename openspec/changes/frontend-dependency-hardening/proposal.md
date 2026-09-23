# Frontend dependency hardening

## Why

The executed workspace acceptance audit on `acd53c0` reports five affected packages: DOMPurify, devalue, nanoid, PostCSS and Vite. The user requested continued frontend/backend completion. This is a bounded security-maintenance follow-up to PR #28, not a new product direction or evidence that an exploit occurred.

## What Changes

- Resolve affected dependencies and necessary transitives within existing major compatibility ranges; raise the direct minimums to known patched DOMPurify/Vite releases.
- Preserve npm-generated integrity/resolution metadata and commit only a reviewed candidate manifest/lock.
- Add a fail-closed dependency-audit workflow and retain exact evidence.
- Run the existing frontend and real-browser/backend acceptance after a clean install of the committed lock.
- Attempt outstanding OpenSpec/GitNexus review tooling in a provisioned read-only runner, distinguishing complete, partial and failed results.

## Impact

Issue #29; branch `codex/frontend-dependency-hardening`, baseline `5f6993cfdb41c38757d130a2792883681435ddba`. Own package manifests/lock, dependency validation workflow/tests if necessary, and this change's artifacts. No application symbols, graph schema, kernel/server/Registry, Port geometry, authority, Agent workflow, user projects or deployment change.

No force upgrades, fabricated integrity hashes, automatic commits from CI, secrets, model calls, main merges or blanket claims of production security.
