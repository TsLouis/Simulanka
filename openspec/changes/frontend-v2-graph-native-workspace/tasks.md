## 1. Spec and impact preparation

- [ ] 1.1 Finalize proposal/design/spec deltas for Frontend v2.
- [ ] 1.2 Run GitNexus impact analysis for `App.svelte`, `litegraph-adapter.ts`, `NodeInspector.svelte`, `ChatDock.svelte`, and `ChatNode.svelte` before editing symbols.
- [ ] 1.3 Confirm no HIGH/CRITICAL impact requires user escalation before implementation.

## 2. Quiet workspace shell

- [ ] 2.1 Extract a minimal workspace shell from `App.svelte` without changing API semantics.
- [ ] 2.2 Add lightweight TopBar and narrow Activity Bar.
- [ ] 2.3 Make Inspector and long discussion surfaces closed by default; preserve explicit reopen paths.
- [ ] 2.4 Keep Graph Canvas as the dominant default surface across supported desktop sizes.

## 3. Zoom-aware Node and Port presentation

- [ ] 3.1 Add stable zoom-density thresholds with no flicker around boundaries.
- [ ] 3.2 Overview zoom shows icon/type + name and hides ports/details.
- [ ] 3.3 Working zoom shows actual input/output port handles.
- [ ] 3.4 Detail zoom shows port names/directions plus PresentationSpec-selected fields.
- [ ] 3.5 Preserve root boundary IO/tunnel semantics and connection eligibility.

## 4. Contextual object interaction

- [ ] 4.1 Add lightweight selection popover with `Ask`, `Open`, and overflow actions.
- [ ] 4.2 Single selection highlights directly related graph structure without entering a named mode.
- [ ] 4.3 Full Inspector opens only on explicit request and remains Registry/affordance-driven.
- [ ] 4.4 Edge and Port selection use the same contextual action model.

## 5. Agent Companion and explicit context

- [ ] 5.1 Add an unobtrusive Agent Companion UI sidecar; it MUST NOT become a semantic graph entity.
- [ ] 5.2 `Ask` on a selection creates/shows pending refs using the existing supplemental-context contract.
- [ ] 5.3 Support an explicit pointer/drag-style attachment path for selected node/edge/port refs where technically practical.
- [ ] 5.4 Show pending refs and preserve context preview before sending.
- [ ] 5.5 Keep long transcript/history accessible on demand rather than permanently occupying canvas space.

## 6. Graph-native Agent expression

- [ ] 6.1 Implement temporary attention/highlight projection that never writes the semantic graph.
- [ ] 6.2 Implement object-attached annotation presentation tied to session/conversation state rather than Node attrs by default.
- [ ] 6.3 Present existing proposed Agent graph changes as visually distinct Drafts.
- [ ] 6.4 Map accepted/rejected product actions to existing authoritative server actions; do not bypass write-matrix checks.
- [ ] 6.5 Use redundant visual cues (line style/opacity/icon) so Draft status is not color-only.

## 7. Product language and pixel visual system

- [ ] 7.1 Replace mechanism-heavy default labels with lightweight product language where semantics remain unchanged.
- [ ] 7.2 Establish restrained pixel tokens for borders, spacing, typography, palette, and Agent state.
- [ ] 7.3 Avoid decorative visual noise that competes with graph readability.

## 8. Verification and docs

- [ ] 8.1 Run frontend type/build checks and relevant tests.
- [ ] 8.2 Run backend regression tests for Registry/affordance/session/context contracts touched by the UI integration.
- [ ] 8.3 Run GitNexus detect-changes before commit/final review.
- [ ] 8.4 Manually verify default canvas, zoom/ports, selection actions, Agent context, and Draft presentation.
- [ ] 8.5 Update `docs/frontend.md` to the accepted implementation and archive/sync the OpenSpec change after acceptance.

## Deferred follow-up

- [ ] D.1 Evaluate reversible Agent auto-apply + Undo only after the current interaction model is validated. Do not weaken frozen write authority in this task by assumption.
