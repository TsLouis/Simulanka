## 1. Explore and resolve
- [x] 1.1 Read actual audit output and primary advisory conditions.
- [x] 1.2 Record bounded ownership, compatibility and non-goals before dependency edits.
- [x] 1.3 Generate candidate manifest/lock with npm and inspect the complete diff.

## 2. Implement
- [x] 2.1 Commit the exact reviewed manifest/lock.
- [x] 2.2 Replace bootstrap resolution with clean-install, fail-closed dependency audit.
- [x] 2.3 Add a disposable real-FileViewer Markdown safety regression without production hooks.

## 3. Verify and deliver
- [x] 3.1 Verify committed-lock audit, frontend tests/check/build.
- [x] 3.2 Run existing Chromium/FastAPI/backend acceptance and new FileViewer safety checks on the committed candidate.
- [x] 3.3 Execute OpenSpec/GitNexus tooling and record limitations without waiving incomplete gates.
- [x] 3.4 Publish exact committed-candidate evidence and final diff review; preserve outstanding parent acceptance.

Verified application/lock/harness revision: `f0aea78f807cfd7ee367b7e975ea4eab8489e59c`. Three CI workflows passed: 60 frontend tests, zero type diagnostics, production build, npm audit zero findings, backend 397 passed / 6 skipped, workspace and FileViewer browser checks without page errors. See verification.md for exact runs and artifacts.

OpenSpec strict passed for both changes. GitNexus runs 35867416702 / 35867815444 executed indexing/impact/detect-changes, but Svelte lookup and graph coverage remain incomplete. Completing task 3.3 means execution and honest reporting, NOT a clean GitNexus gate. The parent gate, full manual/real-project acceptance, merge and deployment remain open.
