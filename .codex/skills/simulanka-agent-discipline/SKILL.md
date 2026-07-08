---
name: simulanka-agent-discipline
description: Apply Simulanka agent-engineering discipline for graph edge proposals, verify/discuss prompts, `simulanka-ops` blocks, and research-cycle claims. Use when Codex needs to propose or check `data_flow` edges, migrate `propose.py` behavior into skills, emit discussion ops, decide whether an agent may write graph semantics, or preserve cite-or-skip and human-verdict boundaries.
---

# Simulanka Agent Discipline

## Core Rules

- Kernel is the only writer. Agents express intent through approved tools or op blocks.
- Cite or skip. An uncited edge or semantic judgment is a guess.
- Prefer few accurate proposals over broad speculative coverage.
- Preserve uncertainty. No op block is better than an uncited or overconfident op block.
- Human verdicts stand. Never overwrite `verdict_by="user"`.
- System measurements are system-owned. Agents may trigger diff, acceptance, metrics, and evidence tools, but may not author their results.
- `propose.py` single-shot flow is retired as the default direction. Carry its discipline into skills and tool-gated workflows.

## Data-Flow Edge Proposals

Use the graph's imported port vocabulary. Propose edges between concrete port ids, not prose module names.

Required proposal attributes:

- `source`: source port id or selector
- `target`: target port id or selector
- `attrs.citation`: source-code, trace, or graph evidence that justifies this edge

Optional attributes:

- `attrs.output_slice`: when one output is sliced or split before reaching the consumer
- `attrs.evidence_locality`: `in_method`, `cross_method`, or `cross_state`

Do not propose self-loops, duplicate known ghosts, edges involving unknown ports, or edges whose only support is intuition.

## Discussion Ops

When a discussion or verify pass needs to write, emit at most one fenced `simulanka-ops` JSON block.

```simulanka-ops
{
  "ops": [
    {
      "op": "set_verdict",
      "edge_id": "edg_...",
      "attrs": {
        "verdict": "correct",
        "verdict_note": "Short evidence-focused reason."
      }
    }
  ]
}
```

Allowed ops:

- `set_verdict`: for `data_flow` edges only; `attrs.verdict` is `correct`, `wrong`, or `uncertain`; `attrs.verdict_note` is required.
- `propose_edge`: requires `source`, `target`, and `attrs.citation`; server forces `source="agent"`, `status="proposed"`, `verdict="unconfirmed"`.
- `withdraw_edge`: only for the agent's own unaccepted proposed ghosts.

Never emit ops for accept, delete user edges, real-domain attrs such as shape checks, `verdict_by`, or human-owned decisions.

## Anchored Conversations

Do not start or design a global free chat. Simulanka agent conversations are anchored to a canvas selection set: one or more nodes or edges. If there is no natural domain entity, anchor to a container such as an experiment, plan directory, or root.

Treat §13.6 batch verification as a special case: the conversation is anchored to the selected disagreement edge set. Chat messages stay in a session tree or sidecar file; graph writes happen only through allowed ops or future deterministic tools. A graph note may point to the conversation anchor, but messages themselves are not research graph nodes.

## Verify/Discuss Stance

For each disagreement:

1. Triage first: agree, disagree, or insufficient evidence.
2. Address the human `verdict_note` directly.
3. Cite the evidence that changes the edge state.
4. Emit no op for unresolved uncertainty unless setting `uncertain` with a note is genuinely useful.

The chat text may explain reasoning even when no op block is emitted.

## Research Claims

Only the analyzer distill step should create supports/contradicts edges from evidence to claims or hypotheses. Operators, checkers, and discussion agents may report observations or run checks, but they do not grade their own work.

Machine evidence can say what was measured. Analyzer distill says what that measurement means.

## Final Checklist

Before returning graph-affecting output:

- Every write path is a tool call or allowed op block.
- Every proposed edge has a citation.
- Port ids and edge ids come from the graph, not memory.
- Human verdicts remain untouched.
- Uncertainty is preserved when evidence is weak.
- System-owned measurements are not paraphrased into new facts without the corresponding tool result.
