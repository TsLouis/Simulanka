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

## 4. Verification

- [x] 4.1 Validate both OpenSpec changes and confirm the new governance change is apply-ready
- [x] 4.2 Check Claude Code project-agent configuration against the installed CLI and scan active files for stale ownership/grill wording
- [x] 4.3 Run GitNexus change detection and review the final diff for documentation-only scope
