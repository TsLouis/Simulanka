## 1. Spec and impact preparation

- [x] 1.1 Finalize proposal/design/spec deltas for Frontend v2.
- [ ] 1.2 GitNexus impact analysis explicitly waived by the user for this iteration; keep review-before-merge.
- [ ] 1.3 GitNexus HIGH/CRITICAL escalation therefore not run; no server/write-authority contract is changed in this slice.

## 2. Quiet workspace shell

- [ ] 2.1 Extract a minimal workspace shell from `App.svelte` without changing API semantics.
- [ ] 2.2 Add lightweight TopBar and narrow Activity Bar.
- [x] 2.3 Make Inspector and long discussion surfaces closed by default; preserve explicit reopen paths.
- [x] 2.4 Keep Graph Canvas as the dominant default surface across supported desktop sizes.

## 3. ComfyUI-baseline Node and Port presentation

- [x] 3.1 Use stable zoom-density thresholds while keeping native LiteGraph port geometry authoritative.
- [x] 3.2 Overview zoom keeps node identity and every real input/output Port handle independently visible; hide Port labels and non-essential card detail only. Mild zoom-out keeps normal labels longer; farther overview zoom redraws Node identity at an approximately screen-stable size instead of letting titles become unreadable pixels.
- [x] 3.3 Working zoom preserves the same independent Port handles and connection anchors; do not merge/stack ports for visual simplification.
- [x] 3.4 Detail zoom restores Port names/directions plus PresentationSpec-selected card fields; Inspector presents port type/shape/confidence as interface metadata.
- [x] 3.5 Preserve root boundary IO/tunnel semantics and connection eligibility; zoom treatment applies only to textual/card density.
- [x] 3.6 Treat ComfyUI as the baseline for ordinary Node Editor behavior (search, ports, links, selection, drag); diverge only where Simulanka graph/research semantics require it.
- [x] 3.7 Prevent native node collapse from collapsing multiple semantic Ports into shared visual anchors; semantic node classes opt out of LiteGraph collapse while boundary projections keep library defaults.
- [x] 3.8 Add a restrained datatype connection palette for common Port types (`tensor`, `scalar`, `any`, etc.) using LiteGraph's native connection palette hooks.

## 4. Contextual object interaction

- [ ] 4.1 Node selection has lightweight `Ask / Why / Open`; overflow/general affordance projection still pending.
- [x] 4.2 Single selection quietly emphasizes the selected Node, one-hop neighbours and direct links; unrelated graph content recedes without entering a named mode. Multi-select disables this attention treatment.
- [x] 4.3 Full Inspector opens only on explicit request and remains Registry/affordance-driven.
- [x] 4.4 Node, Edge and Port surfaces expose the same object-first `Ask Agent` language; Edge keeps simplified Keep/Dismiss/Needs attention actions and server authority.

## 5. Agent Companion and explicit context

- [x] 5.1 Add an unobtrusive Agent Companion UI sidecar; it does not become a semantic graph entity.
- [x] 5.2 `Ask` on a node attaches the explicit ref through the existing supplemental-context contract and opens the Companion composer.
- [x] 5.3 Make hold-`A` pointing the primary graph gesture: while `A` stays held, successive Node/Port/Edge clicks accumulate into one de-duplicated pending RefSet without stealing keyboard focus or moving graph objects. Releasing `A` focuses the Companion composer only when new refs were added. Port hit-testing precedes Node body and Edge uses the persisted Edge hit path; all refs remain gated by `context.attach`. Text inputs do not activate pointer mode.
- [x] 5.4 Keep explicit `Ask Agent` / selection Attach actions as the non-keyboard fallback into the same pending RefSet. Remove the experimental drag-to-Pet/typed-DnD path after pointer validation so the product maintains one direct-manipulation pointing model rather than two competing gestures.
- [x] 5.5 Show pending refs and preserve context preview before sending.
- [x] 5.6 Keep long transcript/history accessible on demand from the Agent Companion; do not project Session trees as canvas windows.
- [x] 5.7 Keep harness/compiler detail progressively disclosed: normal preview shows delivery/source/omission summary while raw compiled payload stays under Technical details.
- [x] 5.8 Pet exposes only quiet micro-states (thinking/context/idea ready/pointing collection); no permanent execution console is introduced. Companion teaches hold-A → point one or more objects → release-A → type as the primary explicit-context gesture.

## 6. Graph-native Agent expression

- [x] 6.1 Implement a turn-scoped Conversation Projection from the server-persisted `user_msg.details.context_bundles[].refs`: exact Node/Port/Edge refs receive temporary Agent attention on Canvas without writing the semantic graph. Projection restores from Session history/branch events and never derives targets from selection/prose/viewport.
- [x] 6.2 Preserve the safe fallback: a turn with exactly one explicit Ref may show compact latest-Agent prose beside that object; multi-ref turns highlight only and never guess which object owns free-form prose.
- [x] 6.3 Present existing proposed/ghost Agent edges (and future proposed nodes) as visually distinct `DRAFT` objects.
- [x] 6.4 Map Keep/Dismiss/Needs attention product actions to the existing authoritative server actions; do not bypass write-matrix checks.
- [x] 6.5 Use redundant visual cues (dash + explicit DRAFT tag + source styling), not color alone.
- [x] 6.6 Define and parse a strict graph-chat `simulanka-projection` sidecar format for `attention`, object-specific `annotation`, and temporary `draft_graph`. Real target refs MUST be a subset of the server-authored explicit Context refs for that turn; free-form prose never creates targets. Projection protocol blocks are hidden from normal Companion/Discussion prose.
- [x] 6.7 Render structured `attention`, `annotation`, and `draft_graph` projections on Canvas. Draft-graph local node ids are conversation-local only; the anchor must be a real explicit Ref. Rendering remains draw-time/UI sidecar and creates no semantic Node/Edge/Port. Draft sketches use an explicit DRAFT container, anchor tether and internal direction arrows so they read as temporary graph ideas rather than ordinary cards.
- [ ] 6.8 Promote the projection transport from graph-chat fenced sidecar blocks to a provider-neutral structured event/tool/details contract without changing the Canvas projection schema. Do this only after the interaction proves useful across real sessions.

## 7. Product language and pixel visual system

- [x] 7.1 Replace mechanism-heavy default edge/selection labels with lightweight product language where semantics remain unchanged.
- [x] 7.2 Establish restrained pixel tokens for borders, spacing, typography, palette, and Agent state.
- [x] 7.3 Remove decorative background/glow treatment that competed with graph readability.

## 8. Node search / creation UX

- [x] 8.1 Keep right-click Add Node search and add ComfyUI-style double-click on empty canvas as an equivalent summon gesture.
- [x] 8.2 Add keyboard result navigation (`↑/↓`, Enter, Esc) and show profile plus input/output count in results.
- [ ] 8.3 Fix the Node + Ports + initial-position creation transaction separately in #17; Frontend v2 MUST NOT hide an incomplete creation failure behind presentation code.

## 9. Verification, performance and docs

- [ ] 9.1 Re-run frontend tests/type/build checks after the latest pointer gesture, zoom readability, graph-loop, structured projection, Companion and transcript changes. Cleanup checkpoint passed earlier, but current head needs fresh verification; no GitHub Actions run exists for the current HEAD.
- [ ] 9.2 Run backend regression tests for Registry/affordance/session/context contracts touched by the UI integration.
- [x] 9.3 GitNexus detect-changes skipped for this user-authorized iteration.
- [ ] 9.4 Manually verify default canvas, readable Node identity across working/overview zoom, persistent independent Ports, no semantic-node port collapse, datatype link colours, search gestures, selection attention/actions, continuous hold-A multi-object pointing on Node/Port/Edge, text-entry isolation, explicit Ask fallback, Draft presentation, turn-scoped fallback projection, structured attention/annotation, and structured draft-graph rendering.
- [x] 9.5 Remove `LGraph.start()` from the read-only/editor graph lifecycle. Canvas rendering remains owned by `LGraphCanvas`; each SSE reload must not start another executable graph loop.
- [ ] 9.6 Stress-test repeated connect/disconnect + SSE reload cycles to confirm the progressive freeze is fixed. If latency still accumulates, profile/coalesce overlapping `load()` calls before changing more interaction code.
- [x] 9.7 Update frontend boundary README/OpenSpec to the accepted graph-native model and pointer-first explicit-context contract.
- [ ] 9.8 Update the long-form `docs/frontend.md` S8 wording so it no longer describes Agent output as message-first; retain server API/domain terminology where it is authoritative.
- [x] 9.9 Remove the superseded drag-to-Agent implementation and its tests/imports after A-pointer validation; no hidden typed-DnD compatibility layer remains in the current frontend source tree.
- [x] 9.10 Add unit coverage for Conversation Projection derivation and structured sidecar safety: latest explicit turn only, exact refs, de-duplication, malformed/invented target rejection, explicit anchor enforcement, transcript protocol stripping, multi-chunk fenced projection parsing, and unfinished-fence concealment during streaming.
- [ ] 9.11 Archive/sync the OpenSpec change after PR #15 acceptance; keep this Draft iteration apply-ready until then.

## 10. Cleanup (#18, PR #15 branch)

- [x] 10.1 Extract Session orchestration into `agent-session.ts`: scope/tree/branch selection, history/recovery, provider capabilities, streaming, stop/fork/archive, explicit refs and preview.
- [x] 10.2 Replace the old dock with `AgentCompanion.svelte` and one opt-in history surface; retain tool events, ContextBundle audit details and lifecycle controls.
- [x] 10.3 Delete floating Session-window projection, drag/position wiring, the obsolete component and compatibility CSS; remove verified unused starter assets and obsolete visual names.
- [x] 10.4 Verify Session/Context behavior, run `npm run check` / `npm run build`, and review the complete cleanup diff. Keep #17, Node Editor interactions, backend/domain/API contracts unchanged; keep PR #15 Draft.

## Deferred follow-up

- [ ] D.1 Evaluate reversible Agent auto-apply + Undo only after the current interaction model is validated. Do not weaken frozen write authority in this task by assumption.
