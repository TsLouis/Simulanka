# Agent Ownership (Codex)

- **Responsibility**: Codex owns the full Simulanka lifecycle across the entire
  repository: exploration, proposal, implementation, verification, commits,
  pushes, GitHub Issue updates, merges, spec sync, and archive. Work never waits
  for Claude availability, authentication, review, or handoff.
- **Worktrees**: implement in `/home/ts/worktrees/simulanka-codex` on a
  `codex/<topic>` branch cut from `main`. Keep `/home/ts/Simulanka` as the
  controlled `main` merge tree and the only checkout with `.venv`. Worktrees
  never live in `/tmp`; do not leave task edits in the primary checkout.
- **Communication = GitHub issues** on the private repo (`gh issue list/view/
  comment`), one issue per topic, close when resolved. The old
  `docs/to-codex.md` / `docs/to-claude*.md` direction files are legacy.
- **Merges to `main`**: Codex commits on the topic branch, performs an
  evidence-backed final diff review, and merges in `/home/ts/Simulanka`. Carry
  GitNexus impact plus ruff / mypy --strict / pytest status and any relevant
  frontend or OpenSpec checks.
- Python: `/home/ts/Simulanka/.venv/bin/python` (absolute path; venv is not
  duplicated into worktrees).
- **Ownership is task-scoped, not directory-scoped.** Codex may work anywhere
  in the repository. One GitHub Issue maps to one OpenSpec change or explicitly
  named task; its implementer owns that vertical slice in the topic branch.
- **One writer per task.** Parallel agents may investigate or verify, but only
  the assigned implementer edits the task's files. The lead agent owns commits,
  pushes, Issue updates, and OpenSpec task checkboxes unless it explicitly
  delegates one of those actions.
- Frozen contracts: §13.6 attrs/write-matrix + server edge endpoints; schema/
  kernel changes require OpenSpec exploration, explicit design/spec coverage,
  GitNexus impact analysis, and explicit Codex review before implementation.
  Product-direction or frozen-contract decisions escalate to the user.
  Authoritative product docs are
  `docs/overview.md` + `kernel.md` / `assembly.md` / `frontend.md`;
  `docs/archive/design.md` is the frozen decision archive. Historical ownership
  labels in the archive are not current assignments.
- **One editor per doc, not just per task.** A task that needs to change an
  authoritative doc claims that file in its Issue; no second task edits the same
  file until the first lands. Task-scoped ownership alone does not prevent two
  parallel tasks from rewriting `frontend.md` at once.

## Development Lifecycle

1. **Explore requirements** with OpenSpec Explore. This stage is read-only:
   investigate the real code, clarify goals/non-goals and surface risks.
2. **Propose the change** with OpenSpec proposal, design, delta specs and tasks.
   Non-trivial implementation starts only after the change is apply-ready.
3. **Apply approved tasks** in a personal worktree/branch. Keep each edit inside
   the selected task and update artifacts first if scope or requirements change.
4. **Review and verify** against specs, targeted tests, GitNexus impact, and the
   repository quality gates. Codex self-reviews the final diff; sync/archive
   only after acceptance.

**Grill is not an initial phase or a universal gate** (confirmed by the user
2026-07-24: on demand, called when they want it). Use a short grill only
when development exposes a concrete conflict in accepted requirements, a
frozen-contract or architecture boundary problem, materially different
evidence-backed approaches, or repeated failure that the current design cannot
explain. If the result changes scope, requirements, design, or tasks, update the
corresponding OpenSpec artifact before resuming implementation. A routine test
failure, missing file location, or ordinary implementation choice is not a
grill.

OpenSpec is the implementation and acceptance source of truth. GitHub Issues
record claims, branches, progress, commits, and review; they do not replace or
add requirements. Do not create a parallel assignment ledger.

## Codex Subagent Routing

Subagents are task templates, not permanent module owners. Spawn them with a
minimal context rather than the full conversation. Multiple read-only agents
may run in parallel; never run two writers against the same worktree/task.

- `gpt-5.6-terra` (default for children): bounded repository inspection,
  test/log triage, routine implementation of one approved task, and ordinary
  diff review. Use low/medium reasoning for search and test collection,
  medium/high for implementation and review.
- `gpt-5.6-sol`: OpenSpec requirements/contract synthesis, cross-module or
  frozen-contract decisions, and high-risk review. Do not use it for routine
  searches or mechanical test execution.
- Spawn scoped children with `fork_turns: "none"` and put all required context
  in the task capsule.

Escalate from Terra to Sol when any of these is true:

- GitNexus reports HIGH or CRITICAL risk;
- the task changes a frozen contract or spans three or more architecture areas;
- it involves transactionality, concurrency, recovery, migration, deletion, or
  another difficult-to-reverse state transition;
- accepted OpenSpec artifacts conflict;
- two materially different implementation/diagnosis attempts fail with
  evidence; or
- an isolated builder/reviewer pass reaches incompatible correctness
  conclusions.

Delegate only where parallelism or isolation actually pays. A child starts
cold and must receive a complete task capsule, so for a bounded lookup the main
session reading the file itself is usually cheaper. Delegation is optional, not
a lifecycle gate; never default to the strongest model.

### The top of the ladder is the user

Escalating reasoning effort or using `gpt-5.6-sol` buys a stronger reading, not
authority. Stop and put the question to the user — with the evidence and the
options — when strong review still cannot resolve it, two substantive attempts
fail, or the decision changes product direction, a frozen contract, or accepted
scope. No model tier is the final arbiter.

### Task capsule and return contract

Every delegated task must state:

- OpenSpec change/task and git baseline;
- one goal plus explicit non-goals;
- worktree and allowed paths;
- relevant contract/spec references and GitNexus impact already known;
- exact validation commands and expected deliverable;
- whether edits are allowed.

Every child returns only:

1. scope handled;
2. evidence with file/symbol references;
3. decision, implementation summary, or test result;
4. unresolved risks and escalation recommendation.

Children do not commit, push, contact GitHub, broaden OpenSpec scope, or mark
tasks complete unless their task explicitly authorizes it.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Simulanka** (3715 symbols, 5753 relationships, 78 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
| Understand architecture / "How does X work?" | `gitnexus-exploring` |
| Blast radius / "What breaks if I change X?" | `gitnexus-impact-analysis` |
| Trace bugs / "Why is X failing?" | `gitnexus-debugging` |
| Rename / extract / split / refactor | `gitnexus-refactoring` |
| Tools, resources, schema reference | `gitnexus-guide` |
| Index, status, clean, wiki CLI commands | `gitnexus-cli` |

<!-- gitnexus:end -->
