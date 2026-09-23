# Verification — workspace-status-resilience

## Verified revision and evidence

Executed revision: `acd53c0348ddccbf0df968ab9464fa2b3e847755`, based on integration PR #27 at `5f1a037e93a64d138af34615475ee67741d8cf24`.

- Frontend CI run 76: https://github.com/TsLouis/Simulanka/actions/runs/35866134944
- Workspace acceptance run 4: https://github.com/TsLouis/Simulanka/actions/runs/35866135023
- Artifact: `workspace-verification`, ID `10751868711`. Includes exact source archive, revision, test logs, JUnit report, production build, browser trace, screenshots and dependency audit. GitHub retention is seven days.

The following results were read from the downloaded artifact, not inferred from a green badge:

| Check | Result |
| --- | --- |
| Frontend unit/integration tests | 60 passed, 0 failed, 0 skipped |
| Svelte/TypeScript | 0 errors, 0 warnings |
| Production build | Passed; bundle-size warning remains |
| Backend pytest | 397 passed, 6 skipped; one upstream FastAPI/httpx deprecation warning |
| Chromium smoke | Six scenario groups completed; no page errors |

## Browser evidence inspected

The harness runs the actual production frontend and FastAPI on a disposable synthetic project. It does not call a model or touch a user project.

1. Real API Port create/delete/rename, connected-Port topology guards and graph reload consistency.
2. Production application startup, live SSE, labelled navigation and disabled initial Back control.
3. Injected layout-save 503 after semantic Node creation; Node is retained. A subsequent graph-read 503 remains visible independently. Dismissal removes only the warning.
4. Actual SSE transport outage, an offline graph commit and reconnect catch-up to the correct node count.
5. Native canvas double-click drill-down and Back/Forward navigation.
6. 390px and 768px toolbar layout without page-level horizontal overflow, keyboard focus visibility and reduced-motion rendering.

Inspected `workspace-model.png`, `workspace-390.png`, and `workspace-warning-and-error.png`: navigation and notices are legible; the graph canvas retains its independent scroll/pan space. A narrow screenshot is not evidence of complete touch-editor support.

The real Vite HTTP proxy test separately exercises Port update/delete forwarding. Same-origin production smoke alone would not establish development-server parity.

## Final source review

Reviewed the full PR diff, including App read ownership/disposal, CreateReloadGate integration, standalone layout warnings, SSE runtime guards/cleanup, template type search, the bounded `/port` proxy and all new tests. No backend/kernel/Registry/Port-geometry or semantic write-authority changes occur in this slice. No additional blocking defect was found in this source review; it is not a substitute for missing tool gates.

## Explicitly unresolved

- GitNexus and OpenSpec CLI were not run in the original execution environment. Keep their task open until a provisioned run supplies actual output. Retrospective analysis cannot be described as pre-edit analysis.
- npm audit reports five affected dependencies: devalue, DOMPurify, nanoid, PostCSS and Vite (two moderate, three high). Fixes are separate dependency-hardening work; this PR does not claim a clean security audit or demonstrated exploitability.
- Full manual Port geometry/authoring, Agent interaction, real-project acceptance, cross-process write serialization and crash recovery remain under their existing tasks.
- No main merge, deployment, existing Issue closure or OpenSpec archive has been performed.
