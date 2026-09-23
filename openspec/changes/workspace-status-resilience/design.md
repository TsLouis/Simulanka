# Design

## Baseline and impact

Based on integration/object-authoring-parity@5f1a037e93a64d138af34615475ee67741d8cf24. Source inspection finds TopBar and subscribeEvents are consumed by App. App.load is called by navigation, entity jumps, refresh, and the debounced SSE path; CreateReloadGate remains the independent Add Node ordering boundary. No server/kernel/Registry symbols change. GitNexus is unavailable and has NOT been executed; this source review is not presented as an equivalent gate. Keep delivery Draft.

## Independent UI status

The primary status and layout warning are separate props and DOM regions. Dismissal only dismisses a notice; it does not imply persistence, retry a request, or undo graph state. Details remain available without forcing an unbounded toolbar height. Both initial-create and drag-save failures use this channel. A later unrelated save does not incorrectly clear an earlier failure.

## Read ownership and live recovery

A ViewRequestGate records an increasing generation and the requested root. Success and failure may mutate UI only when the ticket is still current, the root matches, and the component is alive. New requests supersede old requests even for the same root. Disposal rejects pending work, removes the ResizeObserver, and clears the scheduled reload timer. No network writes are automatically retried.

The server event stream emits ready at its current graph version and only emits later commits. Every valid ready handshake therefore schedules a coalesced graph refresh to catch up startup and reconnect gaps, still through CreateReloadGate. Runtime checks reject malformed event shapes before App can use ref arrays. Consumer callback failures are not mislabeled as parse errors. Native EventSource owns reconnection; close is idempotent and detaches handlers.

## Presentation and verification

Preserve the quiet canvas-first night palette, object grammar, and native Port geometry. Navigation gains accessible labels/current location, readable connection text, keyboard focus and narrow-screen wrapping. A ResizeObserver tracks actual canvas dimensions when toolbar height changes.

A read-only-permission CI workflow runs frontend gates, backend regression, and real Chromium against a disposable synthetic project. Browser fault injection targets layout HTTP responses and the real SSE transport; no user data, model calls, or production test endpoints are involved. Native canvas drill-down and responsive screenshots supplement tests but do not substitute for full manual Port/Agent acceptance. Existing PR acceptance checkboxes remain untouched.

## Browser-discovered search gap

The first Chromium pass confirmed the directory template is named `dir` but displays `directory` as its type. Filtering only labels/names/categories makes that visible type unsearchable. Extend filtering to the already server-supplied profile string, without changing the catalog, parent rules or write permissions. Retain the real browser `directory` search and add direct regressions. The test harness uses actual keyboard navigation before testing focus-visible. Dependency audit results are retained as reports, not represented as remediated findings.
