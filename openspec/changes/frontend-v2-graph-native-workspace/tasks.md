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
- [x] 3.2 Overview zoom keeps node identity and every real input/output Port handle independently visible; hide Port labels and non-essential card detail only.
- [x] 3.3 Working zoom preserves the same independent Port handles and connection anchors; do not merge/stack ports for visual simplification.
- [x] 3.4 Detail zoom restores Port names/directions plus PresentationSpec-selected card fields.
- [x] 3.5 Preserve root boundary IO/tunnel semantics and connection eligibility; zoom treatment applies only to textual/card density.
- [x] 3.6 Treat ComfyUI as the baseline for ordinary Node Editor behavior (search, ports, links, selection, drag); diverge only where Simulanka graph/research semantics require it.
- [ ] 3.7 Prevent any optional node-collapse treatment from collapsing multiple semantic Ports into shared visual anchors; hiding text is allowed, hiding topology is not.
- [x] 3.8 Add a restrained datatype connection palette for common Port types (`tensor`, `scalar`, `any`, etc.) using LiteGraph's native connection palette hooks.

## 4. Contextual object interaction

- [ ] 4.1 Node selection has lightweight `Ask / Why / Open`; overflow/general affordance projection still pending.
- [x] 4.2 Single selection quietly emphasizes the selected Node, one-hop neighbours and direct links; unrelated graph content recedes without entering a named mode. Multi-select disables this attention treatment.
- [x] 4.3 Full Inspector opens only on explicit request and remains Registry/affordance-driven.
- [ ] 4.4 Edge uses simplified contextual actions; Port parity still pending.

## 5. Agent Companion and explicit context

- [x] 5.1 Add an unobtrusive Agent Companion UI sidecar; it does not become a semantic graph entity.
- [x] 5.2 `Ask` on a node attaches the explicit ref through the existing supplemental-context contract and opens the Companion composer.
- [ ] 5.3 Support an explicit pointer/drag-style attachment path for selected node/edge/port refs where technically practical.
- [x] 5.4 Show pending refs and preserve context preview before sending.
- [x] 5.5 Keep long transcript/history accessible on demand; inactive ChatNodes collapse to sidecar tabs instead of permanently occupying canvas space.

## 6. Graph-native Agent expression

- [ ] 6.1 Implement Agent-driven temporary attention/highlight projection that never writes the semantic graph.
- [ ] 6.2 Implement object-attached annotation presentation tied to session/conversation state rather than Node attrs by default.
- [x] 6.3 Present existing proposed/ghost Agent edges (and future proposed nodes) as visually distinct `DRAFT` objects.
- [x] 6.4 Map Keep/Dismiss/Needs attention product actions to the existing authoritative server actions; do not bypass write-matrix checks.
- [x] 6.5 Use redundant visual cues (dash + explicit DRAFT tag + source styling), not color alone.

## 7. Product language and pixel visual system

- [x] 7.1 Replace mechanism-heavy default edge/selection labels with lightweight product language where semantics remain unchanged.
- [x] 7.2 Establish restrained pixel tokens for borders, spacing, typography, palette, and Agent state.
- [x] 7.3 Remove decorative starfield/glow treatment that competed with graph readability.

## 8. Node search / creation UX

- [x] 8.1 Keep right-click Add Node search and add ComfyUI-style double-click on empty canvas as an equivalent summon gesture.
- [x] 8.2 Add keyboard result navigation (`↑/↓`, Enter, Esc) and show profile plus input/output count in results.
- [ ] 8.3 Fix the Node + Ports + initial-position creation transaction separately in #17; Frontend v2 MUST NOT hide an incomplete creation failure behind presentation code.

## 9. Verification and docs

- [ ] 9.1 Run frontend type/build checks and relevant tests (repository currently has no PR CI; local dependency-backed check still required).
- [ ] 9.2 Run backend regression tests for Registry/affordance/session/context contracts touched by the UI integration.
- [ ] 9.3 GitNexus detect-changes skipped for this user-authorized iteration.
- [ ] 9.4 Manually verify default canvas, persistent independent ports across zoom, datatype link colours, search gestures, selection attention, selection actions, Agent context, and Draft presentation.
- [ ] 9.5 Update `docs/frontend.md` to the accepted implementation and archive/sync the OpenSpec change after acceptance.

## Deferred follow-up

- [ ] D.1 Evaluate reversible Agent auto-apply + Undo only after the current interaction model is validated. Do not weaken frozen write authority in this task by assumption.
