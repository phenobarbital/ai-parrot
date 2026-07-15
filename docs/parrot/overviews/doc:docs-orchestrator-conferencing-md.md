---
type: Wiki Overview
title: OrchestratorAgent — Multi-Party Conferencing (`confer`)
id: doc:docs-orchestrator-conferencing-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: LLM-driven `ask()` ReAct loop. Instead of letting an LLM pick which
relates_to:
- concept: mod:parrot.bots.flows.agents
  rel: mentions
---

# OrchestratorAgent — Multi-Party Conferencing (`confer`)

**Feature**: FEAT-223
**Spec**: `sdd/specs/orchestratoragent-multiparty.spec.md`

## What it is

`OrchestratorAgent.confer()` is a **deterministic** alternative to the
LLM-driven `ask()` ReAct loop. Instead of letting an LLM pick which
specialists to call, `confer()` asks **every** selected specialist the **same**
question, cross-pollinates their answers **anonymously**, and lets each agent
**vote** with a confidence score. The consensus is resolved by a
**confidence-weighted tally** — there is no extra LLM synthesis step.

`confer()` is **purely additive**: it does not change the behavior of `ask()`.

## How it works

1. **Round-0 (independent)** — the question is broadcast in parallel
   (`asyncio.gather`) to every selected specialist; each returns one answer.
2. **Round-k (cross-pollinate + vote)** — every agent sees an **anonymous**
   block (`Answer A`, `Answer B`, …; authors are never named, to avoid
   authority bias) and votes via `ask(structured_output=PeerVote)`. A vote
   carries the `chosen_label` (which answer it keeps — possibly its own), a
   `revised_answer`, a `confidence` (0–100), and a `rationale`.
3. **Aggregation** — `scores[label] += confidence`; the label with the highest
   summed confidence wins (ties break deterministically to the lowest label).
   The winning agent's `revised_answer` becomes the new candidate.
4. **Convergence** — rounds repeat until the winning agent is stable across two
   consecutive rounds (`until_convergence=True`) or `max_rounds` is reached.

Every round is persisted to the orchestrator's `ExecutionMemory` for audit.

## Usage

```python
from parrot.bots.flows.agents import OrchestratorAgent

orchestrator = OrchestratorAgent(name="panel")
await orchestrator.add_agent_by_name("data_specialist")
await orchestrator.add_agent_by_name("policy_specialist")
await orchestrator.add_agent_by_name("risk_specialist")

msg = await orchestrator.confer(
    "Should we approve this transaction?",
    agents=None,            # None = all specialists; or pass a subset of names
    max_rounds=3,           # hard cap on vote rounds
    until_convergence=True, # stop early when the winner stabilizes
)

print(msg.content)                     # final answer (winner's revised answer)
result = msg.structured_output         # ConferenceResult
print(result.winner_agent, result.confidence_score, result.converged)
for rnd in result.rounds:              # full audit trail
    print(rnd.round_index, list(rnd.votes.keys()))
```

The returned `AIMessage` has:

- `content` — the final answer (the winning agent's `revised_answer`),
- `structured_output` — a `ConferenceResult` (`is_structured=True`) with the
  winner, aggregated confidence, every `ConferenceRound`, the vote breakdown,
  and a `converged` flag.

## Cost & latency

`confer()` makes **N × (1 + rounds)** LLM calls, where **N** is the number of
specialists on the panel and **rounds** is the number of vote rounds actually
run (≤ `max_rounds`):

- 1 broadcast call per specialist (Round-0), plus
- 1 vote call per specialist per round.

For example, 3 specialists over 3 rounds ≈ `3 × (1 + 3) = 12` calls. Use the
`agents` argument to narrow the panel, and `max_rounds` / `until_convergence`
to bound the number of rounds, when cost or latency matters.

## Graceful degradation

If a specialist cannot emit a structured `PeerVote` (e.g. a provider that does
not support structured output), its vote is **normalized from text**: the agent
keeps its own answer at a neutral confidence (50) and a warning is logged. The
round never fails because one specialist could not produce structured output.
