# Agent Collaboration (Codex ⇄ Claude)

- **Codex works in `/home/ts/worktrees/simulanka-codex`** (branch `codex/dev` or
  `codex/<topic>`, cut from `main`). The primary checkout `/home/ts/Simulanka`
  is Claude's and has `main` checked out. Never leave uncommitted work in the
  other side's tree; worktrees never live in `/tmp`.
- **Communication = GitHub issues** on the private repo (`gh issue list/view/
  comment`), one issue per topic, close when resolved. The old
  `docs/to-codex.md` / `docs/to-claude*.md` direction files are legacy.
- **Merges to `main`**: carry tests, state ruff / mypy --strict / pytest status.
  Codex commits on `codex/*`; Claude merges after cross-review.
- Python: `/home/ts/Simulanka/.venv/bin/python` (absolute path; venv is not
  duplicated into worktrees).
- **Ownership (2026-06-12 final)**: Claude = `frontend/` + `server/` + `cli/`
  + `kernel/` + `storage/` + `schema/` (design-dense, changes via design round
  + Codex review). Codex = agent engineering line: `agent/`, `propose.py`,
  prompts/navigation strategy, 命门 C. Vertical feature lines, not horizontal
  layers — that split was tried and abandoned 2026-06-11.
- Frozen contracts: §13.6 attrs/write-matrix + server edge endpoints; schema/
  kernel changes go through a design round first. Authoritative docs are now
  `docs/overview.md` + `kernel.md` / `assembly.md` / `frontend.md` (single
  writer: Claude); `docs/archive/design.md` is the frozen decision archive
  (section numbers like §13.6/§14.7 still refer to it).

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Simulanka** (3341 symbols, 5094 relationships, 67 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/Simulanka/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Simulanka/clusters` | All functional areas |
| `gitnexus://repo/Simulanka/processes` | All execution flows |
| `gitnexus://repo/Simulanka/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
