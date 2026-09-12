# Verification and review — 2026-09-12

Base: `3a3e2638b761da929499ed5545d44a5db9dc0269`.
Frontend reference: PR #15 at `410eaeff9035ebaf70d573171f789766c9782031`.
Implementation: `codex/backend-write-serialization`, Issue #9.

## Outcome

Implementation and the PR #15 backend design alignment are ready for review. Keep the PR in Draft: the full pytest and mypy gates are not green in this execution environment. Do not merge, sync the new main spec, close #9 or archive this change until those gates have been resolved and rerun.

## Evidence

- Baseline reproduction: two independent Python processes read version 0 behind explicit pipe gates, then finish sequentially. Both return receipt version 1; the manifest is 1 and event versions are `[1, 1]`. Both nodes exist. This proves version loss without depending on random scheduling or a temporary-file collision.
- `pytest -q tests/test_write_serialization.py`: **10 passed**. Coverage includes explicit-version conflict and fresh retry; live-version ordering; checkpoint version count; threads and symlink aliases; independent projects; failed lock/validation release; killed holder; fork reentry; init/import/migration/checkpoint contention; waiting Agent preservation of a new human verdict; and HTTP Keep rechecking state after a library commit.
- Focused integration: **128 passed** across the new tests, checkpoint, server, discussion, Agent Session, context preview, session lifecycle, generic turns, action resolver, profile registry, migrations and bundle/doctor/index tests.
- `python -m ruff check .`: passed.
- `openspec validate backend-write-serialization --strict`: passed.
- `python -m mypy --strict --platform win32 src/simulanka/storage/write_lock.py`: passed. This is static checking only; Windows OS locking has not been runtime-tested here.

Commands use `/home/ts/Simulanka/.venv/bin/python` with `PYTHONPATH=src` from the topic worktree. Python is 3.12.14. No test expectations, existing tests, dependency constraints or type-checking rules were weakened.

## Remaining gates

Full pytest: **389 passed, 3 failed, 6 skipped**. Failures:

- `tests/test_agent_async.py::test_start_agent_run_injects_agent_actor_env`
- `tests/test_runner_async.py::test_start_then_wait_finishes_done`
- `tests/test_runner_async.py::test_wait_timeout_raises`

The original baseline run was 381 passed / 1 failed / 6 skipped. A later run of the three affected cases on unchanged main also failed quick-run completion and wait-timeout; the Agent actor case passed when isolated on main. In the topic full run, each failed run was marked `failed` with `exit_code=None`, while its actual wrapper later wrote exit code 0. The detached-run liveness/marker behavior is unresolved here, rather than established as a regression or dismissed as harmless. These tests must be rerun in the project's normal execution environment before merge.

Full mypy: **the same 10 errors in the same 5 files as unchanged main**. Missing Torch types cause `Any` subclass / unused-ignore errors in the importer and existing Torch fixtures; `types-PyYAML` is also unavailable. Offline installation confirmed these packages are not cached. No error remains in the changed code or new test file. Restore the normal dependencies and rerun the complete strict gate; do not suppress these errors for this PR.

## Final diff review

- Existing function signatures and HTTP route decorators are unchanged. AST comparison confirms modifications are limited to the planned writer functions, the seven graph action handlers and their containing app factory; sibling handler/validator bodies are unchanged.
- The root lock file is stable and excluded from graph hash/bundle/embedded git. Nested entries share one descriptor, thread exclusion precedes OS locking, every acquired descriptor has a close path, and fork cleanup closes inherited descriptors without unlocking the parent's flock.
- Version checks and live-version reads occur inside the lock. State-dependent server and Agent policy checks also occur inside it. Kernel continues to validate structure/record actor while server enforces authority.
- No Provider execution, event-stream loop, Session lifecycle or UI projection code is inside a new lock. Multi-Patch operations retain their previous partial-failure semantics; no crash recovery or Undo claim is made.
- GitNexus 1.6.11 upstream impact was run before existing symbol edits. Graph commits/checkpoint were CRITICAL; dynamically registered HTTP handlers returned UNKNOWN with no static callers, so their routes and server tests were inspected explicitly.
- After index refresh, the structured `detect_changes(scope=all)` result mapped **97 symbols in 16 files and 116 indexed flows**, risk critical, without `error`, `partial` or `truncated` flags. The complete symbol set was reviewed, not only the CLI's shortened display. The global process index still reports trace-budget omissions and FTS is unavailable; source-call searches and AST comparison supplement it. No absence-of-flow claim is used as safety evidence.
- PR #15 received concrete feedback about agent-source badges and disabled accept affordances. Issues #10–#13 received the design dependencies from this change. Their implementations and the frontend task's files were not changed.

## Next acceptance step

Run full ruff / mypy --strict / pytest with the project's normal Torch and YAML typing dependencies and reliable detached-process environment. If the runner failures persist there, diagnose them with a separate explicit scope rather than changing the frozen write contract. Then perform final review, merge, sync the spec and archive.
