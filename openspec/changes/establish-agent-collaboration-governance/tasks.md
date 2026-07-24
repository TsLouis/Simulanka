## 1. Current collaboration entrypoints

- [x] 1.1 Replace permanent Claude/Codex directory ownership in `AGENTS.md` with Issue/OpenSpec task ownership, worktree isolation, single-writer and cross-review rules
- [x] 1.2 Document OpenSpec Explore as the requirement entrypoint and grill as an on-demand development alignment tool
- [x] 1.3 Update `CLAUDE.md` to load the shared collaboration entrypoint and project subagents without creating a second source of truth

## 2. Project subagents and model routing

- [x] 2.1 Add a Haiku read-only context scout and an Opus read-only contract guardian for Claude Code
- [x] 2.2 Add Sonnet slice builder, verification prober and change reviewer definitions with explicit write/commit boundaries
- [x] 2.3 Add Codex Terra/Sol spawn routing, escalation conditions and task capsule contract to `AGENTS.md`

## 3. Residual cleanup

- [x] 3.1 Remove provider-specific ownership wording from active S8 proposal, design and tasks without changing functional requirements
- [x] 3.2 Remove provider-specific ownership wording from authoritative `docs/assembly.md`; retain frozen archive history
- [x] 3.3 Confirm retired `docs/to-codex.md`, `docs/to-claude*.md` and active PTY-route documents are absent from the branch

## 4. Verification（含 2026-07-24 交叉审查修正）

- [x] 4.1 Validate both OpenSpec changes and confirm the new governance change is apply-ready
- [x] 4.2 Check Claude Code project-agent configuration against the installed CLI and scan active files for stale ownership/grill wording
- [x] 4.3 Run GitNexus change detection and review the final diff for documentation-only scope

## 5. Cross-review corrections (Claude, 2026-07-24)

- [x] 5.1 Make branch/merge protocol symmetric (`claude/<topic>` + merge in the primary checkout); the old Codex-commits/Claude-merges wording contradicted the new equal-ownership scenarios
- [x] 5.2 Add per-doc single-editor rule to replace the dropped "authoritative docs single writer = Claude"
- [x] 5.3 Add the user as the top of the escalation ladder (model tiers are not the final arbiter)
- [x] 5.4 Enforce builder write boundaries with `disallowedTools`; add the `mcp__gitnexus__*` tools that the `tools:` whitelist was silently excluding; drop the machine-local `rtk` prefix instruction
- [x] 5.5 Reframe delegation as cost-bearing (cold child re-reads the docs) instead of a blanket "must use project agents"
- [x] 5.6 Record the user's 2026-07-24 confirmation that grill is on-demand, not the default gate
- [ ] 5.7 Open the GitHub Issue this change should have had (one Issue ↔ one change) and retitle Issue #3 away from "Codex 线"
