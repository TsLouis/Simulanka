# To Claude: Repository Review Handoff

Date: 2026-06-12
From: Codex
To: Claude

## Context

I reviewed the Simulanka repository end to end without changing implementation
code. The architecture is coherent: the kernel is centered on Node / Edge /
Port, graph mutations flow through `apply_patch`, and the later frontend /
agent features mostly preserve that boundary.

The main issues I found are not in the core kernel shape. They are at the
edges where CLI defaults, detached agent execution, browser behavior, and
documentation meet.

## Findings For Claude

### P1: Detached task contract is not frozen

Design says a task-bound agent run snapshots the contract onto the run node and
into `<run_dir>/contract.json`, so later edits to the task do not rewrite
history.

Sync agent behavior follows that intent. Detached finalization does not: it
stores the contract at launch, but later `_run_contract_check` reloads the
current task node and checks against whatever the task says at finalize time.

Relevant files:
- `src/simulanka/agent/detached.py`
- `src/simulanka/agent/wrapper.py`
- `src/simulanka/contract.py`
- `tests/test_task_integration.py`
- `docs/design.md` section 5.6

Suggested fix direction:
- At detached launch, keep writing `contract.json`.
- During finalization, reconstruct the contract from that snapshot, not from
  the live task node.
- Add a regression test: start a detached task run, mutate the task attrs before
  finalization, and assert the check uses the original snapshot.

Ownership note: this touches detached agent/task plumbing. It is close to the
runner/agent boundary, but the bug is about kernel-facing contract semantics
and tests, so I think Claude should own the fix unless you want Codex to patch
only the agent-side helper.

### P1: Import CLI default parent is invalid

`simulanka import torch` and `simulanka import baseline` advertise that
`--parent` may be omitted and the model will land at the project root. But the
registry only allows `model` under `directory`, so omitting `--parent` causes a
validation failure.

Relevant files:
- `src/simulanka/cli/import_.py`
- `src/simulanka/importer/torch_export.py`
- `src/simulanka/importer/manifest.py`
- `src/simulanka/registry/builtin.py`
- `tests/test_torch_importer.py`
- `tests/test_baseline_manifest.py`

Suggested design choice:
- Either make `--parent` required for import commands, or default it to an
  existing scaffold directory such as `/baselines` or `/models`.
- The current scaffold does not create `/models`; tests create it manually.
  If `/baselines` is the intended baseline home, document and test that.

### P2: `--track` scope can escape workdir

The CLI help says `--track` is a subdir relative to workdir. Implementation
resolves `(workdir / s).resolve()` and checks existence, but does not enforce
that the result remains under workdir. `--track ../outside` can include an
external directory in the recorded diff.

Relevant file:
- `src/simulanka/agent/wrapper.py`

Suggested fix:
- After resolving, require `p.relative_to(workdir.resolve())` to succeed.
- Add sync and detached tests.

This is agent wrapper code, so Codex can take it if you prefer. It is a small,
well-bounded agent-engineering fix.

### P2: Browser direct CORS blocks edge deletion

Backend CORS allows only `GET` and `POST`, while frontend calls
`DELETE /edge/{edge_id}`. Vite proxy mode hides this, but direct browser calls
from `localhost:5173` to the API server will fail preflight.

Relevant files:
- `src/simulanka/server/app.py`
- `frontend/src/lib/api.ts`
- `tests/test_server.py`

Suggested fix:
- Add `DELETE` to `allow_methods`.
- Add a CORS preflight test for `DELETE /edge/{id}`.

This is clearly Claude-owned under the current design split.

### P3: Project root `.gitignore` fragment is defined but unused

`ROOT_GITIGNORE_FRAGMENT` exists and design says init should write a root
`.gitignore` when absent, excluding `.simulanka/`. Implementation only writes
`.simulanka/.gitignore`.

Relevant files:
- `src/simulanka/layout/project.py`
- `tests/test_init.py`
- `docs/design.md` section 11

Suggested fix:
- On init, if root `.gitignore` does not exist, write the root fragment.
- If root `.gitignore` exists, leave it alone per design.
- Add tests for absent and pre-existing root `.gitignore`.

Claude-owned.

## Verification Status

Commands run:
- `pytest -q`
- `npm run check`
- `npm run build`

Results:
- Python: 159 passed, 6 failed, 1 skipped.
- All 6 Python failures are from missing `yaml` / PyYAML in the current
  environment. `pyproject.toml` already declares `pyyaml>=6`, so this looks like
  an environment/install issue rather than a code failure.
- Frontend typecheck passed.
- Frontend build passed, with warnings from `litegraph.js` direct eval and a
  large bundle.

Current worktree before this document:
- `AGENTS.md` and `CLAUDE.md` had existing GitNexus stats-only edits.
- `.claude/settings.json` was already untracked.

This document is the only file I added.

## Codex Ownership According To Design

Design section 13.5 says:

- Codex owns the agent engineering line:
  - `propose.py`
  - agent prompt and navigation strategy
  - opencode harness problems
  - `evidence_locality` inference via propose / agent output
- Claude owns the rest:
  - kernel
  - schema
  - importer
  - frontend
  - server
  - git checkpoint

Design section 13.6 narrows the current cut further:

- Claude: kernel op extension, server endpoints, frontend verify/discuss panel,
  edge write-back, git checkpoint.
- Codex: opencode session continuation harness, JSON parsing, and prompt shape
  for the discussion loop.

My read: Codex should now focus on the missing conversation harness for the
verify-discuss loop and on making `propose.py` less spike-like:

1. Build the opencode session harness:
   - continue a session non-interactively;
   - parse structured op blocks;
   - keep the agent tool-less and let the server apply filtered ops.
2. Improve proposal quality:
   - use imported graph port vocabulary;
   - preserve citations;
   - infer `evidence_locality`;
   - reduce run-to-run navigation randomness.
3. Keep out of kernel/schema/frontend changes unless Claude explicitly asks
   for a narrow patch.

## Questions For Claude

1. For import defaults, should omitted `--parent` become an error, or should it
   default to `/baselines`?
2. For detached contract freezing, do you want Claude to fix the whole path, or
   should Codex patch the agent-side snapshot/finalize helper?
3. Should Codex proceed next on the opencode session harness spec, assuming the
   existing verify/discuss endpoints and panel are the server/frontend contract?
