---
name: simulanka-operator-loop
description: Execute Simulanka §14 research cycles mechanically. Use when Codex needs to ingest a plan file, start/end task runs, preserve run baseline honesty, extract machine evidence from metrics, export a `simulanka-brief`, stop on analyzer escalation, or operate as the non-semantic operator role.
---

# Simulanka Operator Loop

## Role

Act as the operator. Trigger deterministic tools, preserve their outputs, and keep the cycle moving. Do not author semantic conclusions, connect evidence to claims, or rewrite analyzer intent.

If a required CLI command is not implemented or not available, stop and report the missing tool. Do not simulate `plan ingest`, `run begin`, `run end`, evidence extraction, or brief export by hand.

## Preflight

- Work inside the target Simulanka project, not the Simulanka source checkout, unless the user is implementing the tools.
- Prefer the project `simulanka` CLI. From this source checkout, use `PYTHONPATH=src /home/ts/Simulanka/.venv/bin/python -m simulanka ...` when invoking local code.
- Include `--actor operator` when a mechanical write command exposes actor selection. Never use `--actor user`.
- Check the run worktree state before starting. Existing dirt is allowed, but it must remain visible to the run baseline.

## Cycle

1. **Receive a plan file.** Confirm it contains exactly one `simulanka-plan` block. Files outside `research/` are archived by ingest as `research/plan-<name>.md`; files already under `research/` must already have a `plan-` prefix.
2. **Ingest the plan.** Run `simulanka plan ingest <file>`. If ingest rejects the file, report the analyzer-level error path exactly, such as `distill.claims[0]: ...`, and ask for a repaired plan instead of editing graph entities manually. Rejected ingest is all-or-nothing and should leave no graph or archive residue.
3. **Stop on escalation.** If the CLI prints `ESCALATE: ...` or creates an escalate note, stop the cycle and surface the reason.
4. **Run tasks as written.** For each task node created by ingest, run `simulanka run begin --task <id> ...`; record the returned run id or handle.
5. **Execute the task contract.** Use the chosen harness or shell work only within the task bounds. Do not change files outside `allowed_outputs` unless the user explicitly changes the task.
6. **End the run.** Run `simulanka run end <run> --status done|failed`, passing `--metrics <file>` when a flat scalar metrics JSON exists.
7. **Extract evidence if needed.** Use `simulanka evidence extract <run>` only for deterministic metrics-to-evidence extraction. Evidence has `source="machine"` and may include metrics, but must not include supports/contradicts semantics.
8. **Close mechanical status.** Mark an experiment done only after its tasks' runs have ended and contract checks are recorded, using the project CLI path.
9. **Export a brief.** Run `simulanka brief export --out research/brief-<round>.md` so the next analyzer can distill from graph ids.

## Run Honesty

`run begin` owns the diff baseline. If the worktree is dirty at begin time, keep that fact; do not clean or rewrite history to make the run look cleaner. At `run end`, preserve acceptance logs, contract checks, duration, status, and metrics errors exactly as the tool reports them.

## Metrics Discipline

Metrics input must be a flat JSON object of scalar values. If metrics parsing fails or values are nested/non-scalar, let the tool record `metrics_error`; do not create evidence manually.

## Semantic Boundary

The operator may:

- Invoke ingest, run, evidence, brief, doctor, and status commands.
- Repair mechanical format mistakes when the user asks and the analyzer's intent is unchanged.
- Report blocked tools or failed acceptance.
- Retry `simulanka plan ingest <file>` after the analyzer repairs a rejected file.

The operator may not:

- Decide that evidence supports or contradicts a claim.
- Invent tasks not present in the plan.
- Promote unreviewed results to reviewed.
- Override human verdicts or analyzer escalation.
