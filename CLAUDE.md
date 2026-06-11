# Simulanka

Semi-automated scientific research system built around a content-addressed **Research Graph** (`.simulanka/`) that tracks experiments, runs, code, datasets, and the lineage between them. Python 3.11+, single-user, local-first.

**Status**: Research Graph Kernel **Alpha** complete (milestones 1–14, see `docs/design.md` §9). Working tree on `main` is the source of truth; `docs/design.md` is the authoritative design doc.

## Repository layout

```
src/simulanka/
  kernel/      intent ops, apply_patch, resolver, doctor — the only writers of graph state
  storage/     content-addressed entity store + manifest + event log
  layout/      ProjectLayout, FileRegistry (project layout strategy, not just a registry)
  schema/      Pydantic models for Node / Edge / Port / Manifest / Event
  runner/      exec.py (sync) + detached.py (async/wrapper-script + lazy reconcile)
  agent/       wrapper for codex/claude CLIs; argv via env-var templates, workspace diff
  contract.py  TaskContract model + allowed_outputs glob check + acceptance command runner
  importer/    torch.export → graph nodes (leaf-edge rollup)
  cli/         typer entry points: graph / run / task / file / agent / doctor
tests/         pytest suite; mirrors src/ structure
docs/design.md authoritative design doc; §5.5 (async runner) + §5.6 (TaskContract)
```

## Dev workflow

```bash
.venv/bin/python -m ruff check src tests       # lint
.venv/bin/python -m mypy --strict src tests    # type check
.venv/bin/python -m pytest -q                  # tests
.venv/bin/python -m pytest -x -q               # tests, stop on first failure
simulanka doctor                               # graph health check (entrypoint after install)
```

All three must stay green. Torch is an optional extra (`pip install -e '.[torch]'`); importer tests will skip if torch isn't installed.

## Design discipline

- **Lean first-principles.** No premature abstraction, no half-implementations, no scaffolding for "later". Three similar lines beats an early helper. If the Alpha doesn't do it, at most a one-line note in `docs/design.md`.
- **Kernel writes graph state, nothing else does.** All mutations go through `apply_patch(layout, PatchIntent(...))`. The runner and agent layers never touch storage directly.
- **FileRegistry owns project layout.** Agents/users don't pick paths freely; ask FileRegistry for a kind-appropriate path.
- **Loose coupling for external tools.** Agent CLIs (codex/claude) are wrapped via argv templates with env-var overrides — Simulanka does not duplicate the user's skills/MCP setup.

## What to read first when picking up a new task

1. `docs/design.md` — design rationale, section headers track milestones
2. `.claude/projects/-home-ts-Simulanka/memory/MEMORY.md` (when memory is in context) — user preferences, design decisions, what NOT to do
3. The relevant `tests/test_*.py` — they encode the contract better than prose

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Simulanka** (2220 symbols, 3246 relationships, 37 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
