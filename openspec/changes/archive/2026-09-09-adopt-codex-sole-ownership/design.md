## Context

The accepted governance assumed two active implementers: Codex in a secondary worktree and Claude in the primary checkout. It therefore made cross-provider review and Claude project-agent configuration mandatory. On 2026-09-09 the user explicitly ended Claude participation and assigned the whole project to Codex. Product contracts and evidence gates remain unchanged; only responsibility and review routing change.

## Goals / Non-Goals

**Goals:**

- Make Codex the single accountable project owner without weakening OpenSpec, GitNexus, testing, branch, Issue, or one-writer controls.
- Replace an unavailable external-review gate with an explicit evidence-backed Codex self-review gate.
- Keep the primary checkout as the controlled merge tree and the Codex worktree as the implementation tree.
- Remove active Claude-only files and wording so future sessions follow one unambiguous path.

**Non-Goals:**

- No product feature, runtime Provider, graph schema, write-matrix, or API change.
- No removal of historical references from archived documents or Git history.
- No requirement to use subagents for routine work.

## Decisions

### 1. Codex owns the full lifecycle

The lead Codex session owns exploration, proposal, implementation, verification, commits, pushes, Issue updates, local-main merges, spec sync, and archive. This removes handoff latency and the obsolete Claude authentication dependency. The user remains the only authority for product-direction or frozen-contract decisions.

### 2. Review becomes evidence-backed self-review

Before merge, Codex MUST review the final diff against the selected OpenSpec artifacts, run GitNexus change detection, and report relevant quality gates. Optional independent Codex review agents MAY be used when isolation or risk justifies their cold-start cost, but they are not a universal gate and do not own the final decision.

### 3. Worktree isolation remains

Implementation continues on `codex/<topic>` in `/home/ts/worktrees/simulanka-codex`; `/home/ts/Simulanka` remains the controlled `main` merge and shared virtual-environment checkout. This preserves the useful safety boundary without pretending another provider owns the primary tree.

### 4. Remove Claude-only active configuration

Delete root `CLAUDE.md` and `.claude/` project configuration. Git history and archived OpenSpec retain the old collaboration record. `AGENTS.md` becomes the only active agent-governance entrypoint.

## Risks / Trade-offs

- [Self-review can miss an implementation bias] → Require spec-by-spec diff review, GitNexus impact evidence, and proportional tests; use an isolated Codex reviewer for high-risk work when useful.
- [Sole ownership could weaken separation of duties] → Keep one-writer discipline, task/doc claims, topic branches, reproducible gates, and user escalation for product or frozen-contract changes.
- [Removing Claude files loses convenient historical context] → Preserve all prior content in Git history and the archived governance change.

## Migration Plan

1. Archive the completed two-provider governance change as the historical baseline.
2. Update its main capability spec with this delta.
3. Rewrite `AGENTS.md` to the Codex-only operating path.
4. Remove `CLAUDE.md` and `.claude/` active configuration.
5. Replace stale external cross-review gates in active OpenSpec changes with Codex evidence-backed final-diff review.
6. Validate OpenSpec, review the final diff, update the governance Issue, and merge from the Codex topic branch.

Rollback is a Git revert of the governance commit; it does not affect product data or APIs.

## Open Questions

None. The user made the ownership decision explicitly.
