## Why

The user has ended Claude participation and assigned ongoing Simulanka ownership to Codex. The repository still requires Codex-to-Claude handoffs and cross-review, so its written governance now blocks otherwise accepted work and misstates who has authority.

## What Changes

- **BREAKING**: replace the Codex–Claude collaboration model with Codex sole ownership for implementation, review, commits, pushes, Issue updates, merges, and OpenSpec closure.
- Remove Claude cross-review and Claude authentication as lifecycle gates; Codex performs evidence-backed self-review before merge.
- Retain task-scoped branches, one-writer discipline, authoritative-document claims, GitHub Issue coordination, OpenSpec lifecycle, GitNexus impact checks, and repository quality gates.
- Allow optional read-only or explicitly delegated Codex subagents when parallelism materially helps, while the lead Codex session remains accountable and the user remains the final authority.
- Remove obsolete Claude-only repository configuration and references instead of leaving a second active governance path.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `agent-collaboration-governance`: replace two-agent ownership and mandatory cross-review with Codex sole ownership and evidence-backed self-review.

## Impact

- Governance: `AGENTS.md`, GitHub Issue ownership/review records, branch and merge procedure.
- Repository configuration: root `CLAUDE.md` and `.claude/agents/` become obsolete.
- Active OpenSpec changes: replace stale external cross-review gates with Codex evidence-backed final-diff review.
- No product API, schema, kernel, server, frontend, or persisted data contract changes.
