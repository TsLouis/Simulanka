# Researcher Remote Development Handoff

Date: 2026-05-14
Target remote workspace: `~/Simulanka`

## Current Decision

The local `Researcher` MVP should be treated as a reference and smoke-test prototype, not as the final development base. Formal development will continue remotely under `~/Simulanka`.

The product direction is not a thin incremental MVP. The first serious milestone should be a robust Research Graph Kernel: a safe node-edge-port foundation that all users, CLIs, agents, parsers, runners, and frontends must use for state changes.

## Core Architecture Principles

1. All system state changes must go through system interfaces.
   - No direct edits to graph entity files by users, agents, CLIs, or frontend code.
   - Direct file import/repair should go through explicit `graph import` or `graph doctor` flows.

2. The state model is:
   - `GraphPatch` is the only write path.
   - Event log records what happened.
   - Entity files record current state.
   - Manifest locks versions/hashes and detects inconsistency.
   - SQLite or any DB is a rebuildable query index, not the source of truth.

3. Filesystem hierarchy is a navigation and ownership contract.
   - Directory/node hierarchy should be managed by `ProjectLayout` and `FileRegistry`.
   - Directory nodes can be real or virtual, but they should be represented in the graph with `contains` edges.
   - Semantic relations remain graph edges, not directory hacks.

4. The canonical graph is strongly typed and extensible.
   - Use a small but hard type registry for node, edge, port, and directory types.
   - Use declarative constraints for common rules.
   - Use validator hooks for complex rules.
   - Validator hooks should validate and diagnose, not secretly modify state.

5. Agent-facing writes should be compact.
   - Agents should emit short `PatchIntent`, not full verbose canonical patches.
   - Kernel resolves selectors to stable IDs, validates, then expands into canonical `GraphPatch`.
   - Ambiguous selectors must fail with candidates; do not guess.

6. Canonical committed state must use stable IDs.
   - Selectors like `conv1.out` are allowed only as input conveniences.
   - Events, entity files, canonical patches, and indexes should use stable IDs.

7. The graph needs migration and doctor from the start.
   - `schema_version`, `registry_version`, `graph_version`.
   - `graph migrate --dry-run`, `graph migrate`, `graph doctor`.
   - Migration should also go through Kernel APIs and produce auditable events.

8. Storage granularity:
   - Entity-per-file for nodes, edges, ports.
   - Segmented JSONL event logs.
   - SQLite index can be deleted and rebuilt.

## Directory and File Model

Recommended project-local layout:

```text
project-root/
  .researcher/
    manifest.json
    graph/
      nodes/
      edges/
      ports/
      events/
      proposals/
      indexes/
    tasks/
    runs/
    artifacts/
    logs/
    cache/
```

High-level rule:

- Project state is local to the project under `.researcher/`.
- Global home is only for config, runner profiles, project registry, and cache.
- Core graph metadata should be versionable.
- Large, temporary, rebuildable, or sensitive outputs should not be core state.

Files and directories are first-class graph objects:

- Files are not just attachments.
- Graph stores file metadata, hash, path, kind, and relations.
- File contents remain in filesystem/git/artifact store.
- External repos or model directories may be referenced, but each binding needs explicit read/write policy.

Default file binding modes:

- `reference`: record path and metadata only.
- `snapshot`: copy key small immutable evidence/config into artifacts.
- `generated`: runner/system output managed under artifacts/runs.

## Canvas and Frontend Principle

Only one canvas is needed: `GraphCanvas`.

Do not create separate model/research/task/file canvases. They are all graph scopes shown through the same canvas.

Navigation should follow directory/node hierarchy:

- Entering a node is like entering a directory/scope.
- Default display is children/scope contents.
- Neighborhood/related semantic edges are optional expansions, not the default.

The frontend is a visual shell over the same Graph Kernel API. It must not own separate graph mutation logic.

## Model Parser Boundary

The model parser is a plugin/importer above Graph Kernel, not part of Kernel internals.

Flow:

```text
PyTorch importer -> PatchIntent -> resolver -> validator -> GraphPatch -> commit
```

Parser first milestone:

- Static AST importer first.
- Runtime trace importer later as optional enhancement.
- Default granularity is module-level graph.
- Operation/tensor-level expansion should be on demand.
- LLM can help name, explain, summarize, and propose, but cannot alone define canonical model structure.

## OpenResearch Atom Idea

OpenResearch's atom idea should become a semantic layer on top of Graph Kernel, not a separate state system.

Atoms are graph nodes with research semantics:

- question
- hypothesis
- claim
- evidence
- experiment
- task
- run
- artifact
- file
- note
- decision

Relations are typed edges. Do not introduce another atom storage model.

## Agent and Runner Roles

Assistant agent:

- Small model, low-cost, event-driven plus lightweight heartbeat.
- Handles scheduling, blockage clearing, bug records, risk reports, temporary communication, and proposal summaries.
- Can create tasks, notes, bug reports, proposals, risk reports.
- Should only auto-commit very low-risk maintenance operations.
- Risk policy still needs a dedicated later design pass.

Codex/Claude:

- Do real development and heavy work.
- Should receive explicit `TaskContract`.
- Should return `RunResult`, code diff, artifacts, logs, and PatchIntent/GraphPatch proposal.
- Should not bypass Graph Kernel.

Graph Kernel:

- Final validation and commit authority.
- All accepted state changes go through it.

TaskContract, RunResult, Proposal:

- Must be graph-native core objects, not temporary runner internals.
- Execution isolation should use git branch/worktree or equivalent git-controlled flow.
- Detailed branch/worktree mechanics can be decided later.

## Kernel Alpha Milestone

First formal milestone should be `Research Graph Kernel Alpha`, not full parser/frontend/agent product.

Kernel Alpha should deliver:

- `ProjectLayout`
- `FileRegistry`
- graph schema for node/edge/port/directory/file
- `contains` edge plus semantic edge support
- type registry and validation
- `PatchIntent -> GraphPatch -> event/files/index`
- manifest/version/hash consistency
- CLI/API entrypoints
- `graph doctor`
- export/import basics
- SQLite index rebuild

Kernel Alpha should be validated by CLI first, not UI or agent demo.

Example acceptance flow:

```text
researcher init ./demo-project
researcher graph node create --type directory --path /models
researcher graph node create --type model --name TinyNet --parent /models
researcher graph node create --type module --name conv1 --parent /models/TinyNet
researcher graph node create --type module --name bn1 --parent /models/TinyNet
researcher graph port create conv1 --name out --direction output --type data
researcher graph port create bn1 --name in --direction input --type data
researcher graph connect conv1.out bn1.in --type data_flow
researcher graph inspect /models/TinyNet
researcher graph doctor
researcher graph export --format json
```

Must verify:

- entity files created
- events recorded
- manifest version/hash updated
- index can be rebuilt
- illegal connections rejected
- direct file tamper is detected by doctor
- PatchIntent dry-run/apply works
- selector ambiguity fails clearly

## Local MVP Status to Carry Forward

Local repo:

```text
/Users/ts_mac/Documents/Codex/Researcher
```

The last committed MVP baseline was:

```text
eb5570a Complete Researcher graph MVP baseline
```

After that, a frontend/node-connection bugfix was made but not committed yet. It changed:

```text
apps/researcher-base/src/deepscientist/daemon/api/handlers.py
apps/researcher-base/src/deepscientist/research_graph/service.py
apps/researcher-base/src/ui/src/components/workspace/ResearcherMvpWorkspace.tsx
apps/researcher-base/tests/test_graph_api.py
```

Bug fixed:

- Frontend was dropping `sourceHandle` and `targetHandle` when connecting nodes.
- Backend created fresh implicit ports instead of using the dragged ports.
- Nodes without ports had no node-level handles.

Verification already run locally:

- focused graph API/service tests: 17 passed
- frontend build passed
- real API connection preserved exact source/target port IDs
- GitNexus detect found medium scope, no high/critical warning

Treat this bugfix as useful reference behavior for remote development, but do not assume the current local MVP should become the final codebase.

## Reference Reuse Direction

Use references as design/code references, not direct fork targets.

DeepScientist is useful for:

- workspace lifecycle
- runner abstraction
- artifact service
- human review patterns
- daemon/API shell
- Codex/Claude runner details

OpenResearch is useful for:

- atomized research graph ideas
- typed relation thinking
- graph traversal/prompt context
- task/runtime boundaries
- patch/error handling ideas

Formal implementation should be clean and modular under the remote `~/Simulanka` workspace.

