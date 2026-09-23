# Verified delivery — frontend-dependency-hardening

## Exact executed revision

Application, dependency lock and browser harness revision: `f0aea78f807cfd7ee367b7e975ea4eab8489e59c`.

- Frontend CI run 78: https://github.com/TsLouis/Simulanka/actions/runs/35868971623
- Workspace acceptance run 6: https://github.com/TsLouis/Simulanka/actions/runs/35868966638
- Dependency hardening run 3: https://github.com/TsLouis/Simulanka/actions/runs/35868966708

All three completed successfully. Downloaded artifacts were opened and inspected, not inferred solely from badges:

| Verification | Executed result |
| --- | --- |
| npm ci from committed package-lock.json | Passed; files unchanged after installation |
| Full npm audit, including development dependencies | 0 findings in all severity categories, down from 5 in workspace baseline |
| Frontend unit/integration tests | 60 passed, 0 failed, 0 skipped |
| Svelte and TypeScript checks | 0 errors, 0 warnings |
| Production build | Passed; existing LiteGraph direct-eval and chunk-size warnings remain |
| Full backend pytest | 397 passed, 6 skipped, 1 upstream deprecation warning |
| Actual Chromium / FastAPI workspace smoke | Six scenario groups pass; no page errors |
| Actual production FileViewer Markdown safety | All seven assertions/check groups pass; no page errors or fixture script execution |
| OpenSpec strict | Both workspace-status-resilience and frontend-dependency-hardening pass |

The six pytest skips concern optional Torch-dependent modules/scenarios; this run does not verify actual model imports. Full ruff/mypy were not rerun in this dependency-only slice. No backend production symbols change.

## Browser evidence

Workspace smoke verifies real Port HTTP round trips and connected-Port topology guards, live startup, semantic Node retention after a failed layout write, independent warning/error dismissal, real SSE outage and offline-commit recovery, native drill-down plus history navigation, and 390/768px toolbar/focus behavior.

The additional FileViewer check registers a real disposable Markdown file and opens it through the actual production UI. Raw file bytes are preserved. Ordinary headings, bold text, safe links and code remain; script/iframe tags, inline event handlers and javascript URLs are removed; none of the harmless marker probes execute. It does not mock or replace the production sanitizer. The intentionally missing test image and literal unsafe HTML code are fixture content, not application errors.

Inspected workspace-model, narrow-workspace, warning/error and markdown-safety screenshots. Synthetic browser acceptance is not full manual Port geometry, Agent interaction, touch-editor or real-project acceptance.

## Reproducibility

Workspace artifact `workspace-verification` ID 10753961429 contains exact source.zip, built frontend, revision, frontend/backend logs, JUnit report, audit, browser results, screenshots and trace. Security artifact `dependency-security-verification` ID 10753302956 contains exact package files, audit, version/hash records, OpenSpec/frontend logs, FileViewer screenshot/results/trace. Source.zip's committed lock matches the reviewed npm candidate byte-for-byte.

- package.json SHA256: `fa1fbfddcb9982ff6627eee9e25758e0282f24afef09b268f0f7d83e4a12bbdd`
- package-lock.json SHA256: `5340bd6d603bbb27ce80daf8bfcb8ab4b3931ab48a65ffe45d315b78e184d411`

GitHub retention is seven days for workspace evidence and fourteen days for security evidence. Preserve downloaded copies when longer retention is needed.

## Final review and remaining boundaries

Reviewed the complete manifest/lock diff, authentic integrity data, supported major/peer/Node ranges, test fixture isolation, CI read-only permissions and exact committed-lock install path. Bootstrap resolution is gone: the lasting audit cannot silently fix, ignore or reinterpret findings as success. OpenSpec validation is scoped to active change directories so later archival does not break unrelated pull requests.

GitNexus was executed but remains incomplete for Svelte embedded functions and truncated execution-flow coverage. See review.md for failed run IDs, UNKNOWN results and successful partial change detection. No retrospective result is represented as pre-edit analysis or a complete safety gate.

Zero npm findings are not a guarantee of zero vulnerabilities. This task does not implement cross-process graph-write serialization, multi-file crash recovery or real Agent/model acceptance, and does not merge or deploy any branch. PR #30 remains stacked on #28; existing #15/#19/#27 acceptance is unchanged.
