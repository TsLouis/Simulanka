---
name: simulanka-plan-author
description: Write or revise Simulanka research plan Markdown files for the §14 analyzer role. Use when Codex needs to draft, repair, or review a plan file with exactly one `simulanka-plan` JSON block, distill a `simulanka-brief`, create questions/hypotheses/experiments/tasks from graph ids, or handle analyzer `escalate` semantics.
---

# Simulanka Plan Author

## Role

Act as the analyzer. Produce a plan document that preserves free-form reasoning in prose and exposes only the machine-readable commitments in one valid JSON block.

Do not run tools, create graph nodes directly, or translate the plan into PatchIntent. `plan ingest` is the deterministic writer.

## Required Shape

Create Markdown with prose plus exactly one fenced block tagged `simulanka-plan`. The block must be strict JSON: no comments, no trailing commas.

`distill` and `plan` are both optional parsing regimes. An entirely empty block is rejected, so include at least one distill item, one new plan item, or a non-null `escalate`.

```simulanka-plan
{
  "plan": {
    "questions": [
      {"lid": "q1", "body": "What should be checked next?"}
    ]
  }
}
```

## Distill First

Prefer to use `distill` to review old graph state before opening new work when a `simulanka-brief` gives relevant ids. This is loop discipline, not a schema requirement; omit `distill` when there is nothing concrete to review.

- Reference existing graph ids directly for prior evidence, claims, hypotheses, questions, runs, or tasks.
- Use local lids only for `distill.new_claims`; `distill.edges[].target` may point at one of those lids.
- Add `supports` or `contradicts` edges only from evidence ids to claim or hypothesis ids.
- Put a short `note` on every semantic edge or status/verdict update.
- Treat `claims[].status` as the analyzer's judgment snapshot: `open`, `supported`, or `refuted`.
- Treat `hypotheses[].verdict` as the analyzer's qualitative conclusion. The accepted terms are `unconfirmed`, `correct`, `wrong`, `uncertain`, and `disputed`.

Never invent graph ids. If the brief does not provide an id needed for distillation, say so in prose and leave that relation out.

## Plan New Work

Use `plan` for new entities. `lid` values are local to the block.

Lids must start with a letter, contain only letters, digits, or underscores, and be at most 64 characters. They are block-wide unique across new claims, questions, hypotheses, experiments, and explicit or derived tasks. Do not use `escalate`; it is reserved for the escalate note.

- `questions[]`: `{"lid": "q1", "body": "..."}`
- `hypotheses[]`: `{"lid": "h1", "body": "...", "addresses": "q1"}` or point `addresses` at an existing graph id.
- `experiments[]`: `{"lid": "e1", "goal": "...", "tests": "h1", "tasks": [...]}`
- `tasks[]`: use the TaskContract words exactly: `goal`, `allowed_outputs`, `acceptance`, `budget_time_seconds`; optional `lid` defaults to `t1`, `t2`, ... with explicit task lids occupying names first.

Tasks must be mechanical and executable by an operator. Keep `acceptance` to commands or checks the system can run. Keep `allowed_outputs` narrow enough that a diff can be judged.

## Escalation

Set `"escalate": {"reason": "..."}` only when the analyzer wants the cycle to stop for human or stronger-model attention. The operator must stop on non-null `escalate`.

## Output Checklist

Before returning a plan:

- Exactly one `simulanka-plan` block exists.
- The JSON parses as JSON.
- The block is not empty.
- Existing ids appear only where existing ids are allowed.
- Local lids match the charset, are unique inside the block, and never use `escalate`.
- Every task has a concrete goal and mechanically checkable bounds.
- No supports/contradicts relation is written without an evidence id and a note.
