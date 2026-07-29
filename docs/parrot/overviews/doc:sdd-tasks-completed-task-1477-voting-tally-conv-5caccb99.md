---
type: Wiki Overview
title: 'TASK-1477: Structured voting, weighted tally, convergence loop, and confer()'
id: doc:sdd-tasks-completed-task-1477-voting-tally-convergence-confer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 3 of the spec (§2 Overview/Component Diagram, §3 Module
  3) — the heart
relates_to:
- concept: mod:parrot.bots.flows.agents
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.models.conference
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1477: Structured voting, weighted tally, convergence loop, and confer()

**Feature**: FEAT-223 — Multi-Party Conferencing for OrchestratorAgent
**Spec**: `sdd/specs/orchestratoragent-multiparty.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1476
**Assigned-to**: unassigned

---

## Context

Implements Module 3 of the spec (§2 Overview/Component Diagram, §3 Module 3) — the heart
of the feature. Wires the broadcast (TASK-1476) into a cross-pollination + structured
vote loop, aggregates votes by confidence-weighting (deterministic), iterates until
convergence, and exposes the public `confer()` method that returns an `AIMessage` whose
`structured_output` is a `ConferenceResult`.

---

## Scope

- Add `async def _collect_votes(self, question, peer_block, label_to_agent, agents) -> Dict[str, PeerVote]`:
  fan-out `agent.ask(question + peer_block, structured_output=PeerVote)` over the panel;
  read `AIMessage.structured_output`. **Graceful fallback**: if a specialist returns no
  `structured_output`, parse its `content` into a `PeerVote` with a default
  `confidence` (50) and a warning log — the round must not fail.
- Add `def _tally_weighted_votes(self, votes) -> tuple[str, Dict[str, float]]`:
  `scores[chosen_label] += vote.confidence`; winner = label with max score;
  deterministic tie-break = lowest label (alphabetical). Returns `(winner_label, breakdown)`.
- Add public `async def confer(self, question, agents=None, max_rounds=3, until_convergence=True, **kwargs) -> AIMessage`:
  - `self._init_execution_memory(question)`.
  - Round-0: `answers = await self._broadcast_round(question, agents)`.
  - Loop `k = 1..max_rounds`: build anonymous block → collect votes → tally →
    build a `ConferenceRound` and persist it to `self._execution_memory` → update the
    candidate answers from the winners' `revised_answer` → if `until_convergence` and the
    winning agent is the same as the previous round, `break`.
  - Build `ConferenceResult` and return `AIMessage(content=final_answer,
    structured_output=ConferenceResult, is_structured=True)`.
- Extend the unit test module with voting/tally/convergence tests.

**NOT in scope**: the models (TASK-1475), broadcast/anon-block helpers (TASK-1476),
end-to-end integration + no-regression tests (TASK-1478), exposing via
`ask(mode="conference")` (deferred open question §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py` | MODIFY | Add `_collect_votes`, `_tally_weighted_votes`, `_build_conference_result`, public `confer()` |
| `packages/ai-parrot/tests/test_orchestrator_conference.py` | MODIFY | Add voting/tally/convergence tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-05. Monorepo paths under `packages/ai-parrot/src/`.

### Verified Imports
```python
import asyncio
from typing import Dict, List, Optional
from parrot.models.conference import PeerVote, ConferenceRound, ConferenceResult  # TASK-1475
from parrot.models.responses import AIMessage          # verified: parrot/models/responses.py:72
from parrot.bots.flows.core.result import NodeResult   # used by ExecutionMemory.add_result
```

### Existing Signatures to Use
```python
# parrot/bots/base.py
async def ask(self, question: str, ...,
              structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None,
              use_conversation_history: bool = True, use_tools: bool = True,
              **kwargs) -> AIMessage                                  # L718-740
#   -> passing a bare BaseModel subclass is OK; base wraps it in StructuredOutputConfig @ L1076-1082

# parrot/models/responses.py
class AIMessage(BaseModel):                                           # L72
    content: ...                                                     # (text payload)
    structured_output: Optional[Any]                                # L194  (None if model didn't produce one)
    is_structured: bool                                             # immediately after L194

# parrot/models/outputs.py
@dataclass
class StructuredOutputConfig:                                        # L75
    output_type: type                                              # L77

# parrot/bots/flows/agents/orchestrator.py
def _init_execution_memory(self, question: str)                     # L199  (sets self._execution_memory)
specialist_agents: Dict[str, Union[BasicAgent, AbstractBot]]        # L38

# parrot/bots/flows/core/storage/memory.py
class ExecutionMemory(VectorStoreMixin):                            # L19
    results: Dict[str, NodeResult]                                  # L33
    def add_result(self, result: NodeResult, vectorize: bool = True) -> None  # L55

# parrot/bots/flows/core/result.py
@dataclass
class NodeResult:                                                   # L39
    node_id: str; node_name: str; task: str; result: Any           # L63-66
    ai_message: Optional[Any] = None                               # L67
```

### Does NOT Exist
- ~~`OrchestratorAgent.confer` / `_collect_votes` / `_tally_weighted_votes`~~ — create them.
- ~~`AgentCrew.run_conference`~~ — not a thing; `run_parallel` is pattern-only.
- ~~A built-in confidence-weighted tally~~ — implement it here.
- ~~`AIMessage.confidence` / `.winner`~~ — not real fields; the result lives in `structured_output`.

---

## Implementation Notes

### Pattern to Follow
```python
async def confer(self, question, agents=None, max_rounds=3, until_convergence=True, **kwargs):
    self._init_execution_memory(question)
    answers = await self._broadcast_round(question, agents)   # {agent: text}
    rounds, prev_winner, converged = [], None, False
    for k in range(1, max_rounds + 1):
        block, label_to_agent = self._build_anonymous_peer_block(answers)
        votes = await self._collect_votes(question, block, label_to_agent, agents)
        winner_label, breakdown = self._tally_weighted_votes(votes)
        winner_agent = label_to_agent[winner_label]
        rnd = ConferenceRound(round_index=k, answers={lbl: answers[label_to_agent[lbl]]
                              for lbl in label_to_agent}, label_to_agent=label_to_agent, votes=votes)
        rounds.append(rnd)
        self._execution_memory.add_result(NodeResult(
            node_id=f"conference_round_{k}", node_name="conference", task=question,
            result=rnd.model_dump(), ai_message=None), vectorize=False)
        # next candidates = each agent's revised answer
        answers = {a: v.revised_answer for a, v in votes.items()}
        if until_convergence and winner_agent == prev_winner:
            converged = True
            break
        prev_winner = winner_agent
    final = self._build_conference_result(winner_agent, answers, breakdown, rounds, converged)
    return AIMessage(content=final.final_answer, structured_output=final, is_structured=True)
```

### Key Constraints
- Async-first throughout; vote collection uses `asyncio.gather`.
- Deterministic tie-break (lowest label). Document it in code + test it.
- Fallback default `confidence = 50` when a specialist can't produce structured output;
  log a warning with `self.logger`.
- `final_answer` = the winning agent's `revised_answer`; `confidence_score` = winner's
  aggregated score from `breakdown`.
- Persist each round to `ExecutionMemory` with `vectorize=False` (no embedding required).

### References in Codebase
- `parrot/bots/abstract.py:3876` — real `ask(..., structured_output=Model)` usage; reads
  `response.structured_output`.
- `parrot/bots/flows/crew/crew.py:1966` — `asyncio.gather` fan-out.
- `parrot/tools/agent.py:271-295` — how AgentTool writes results into ExecutionMemory.

---

## Acceptance Criteria

- [ ] `confer()` exists with the spec signature and does NOT alter `ask()` behavior.
- [ ] Round-0 broadcasts the same question in parallel to the selected panel.
- [ ] Votes are gathered via `agent.ask(structured_output=PeerVote)`; an agent may vote
      for its own label and it counts.
- [ ] `_tally_weighted_votes` returns the label with the highest summed `confidence`;
      ties resolved to the lowest label, deterministically.
- [ ] `until_convergence=True` stops early when the winning agent repeats; never exceeds
      `max_rounds`.
- [ ] A specialist without structured output does NOT break the round (fallback vote).
- [ ] `confer()` returns `AIMessage` with `content=final_answer`,
      `structured_output` a `ConferenceResult`, `is_structured=True`; each round is in
      `self._execution_memory.results`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/test_orchestrator_conference.py -v`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py`.

---

## Test Specification

```python
# Extends packages/ai-parrot/tests/test_orchestrator_conference.py

class _VotingAgent:
    """Fake specialist whose ask() returns an AIMessage-like with structured_output=PeerVote."""
    def __init__(self, name, answer, chosen_label, confidence):
        self.name = name
        self._answer, self._label, self._conf = answer, chosen_label, confidence
    async def ask(self, question, structured_output=None, **kw):
        from parrot.models.conference import PeerVote
        class _R:
            content = self._answer
            is_structured = True
            structured_output = PeerVote(chosen_label=self._label, revised_answer=self._answer,
                                         confidence=self._conf, rationale="r")
        return _R()


class TestVotingAndConfer:
    def test_weighted_tally_winner(self, orch):
        from parrot.models.conference import PeerVote
        votes = {
            "data":   PeerVote(chosen_label="A", revised_answer="x", confidence=90, rationale="r"),
            "policy": PeerVote(chosen_label="B", revised_answer="y", confidence=40, rationale="r"),
        }
        winner, breakdown = orch._tally_weighted_votes(votes)
        assert winner == "A" and breakdown["A"] == 90

    def test_tie_break_lowest_label(self, orch):
        from parrot.models.conference import PeerVote
        votes = {
            "data":   PeerVote(chosen_label="B", revised_answer="y", confidence=50, rationale="r"),
            "policy": PeerVote(chosen_label="A", revised_answer="x", confidence=50, rationale="r"),
        }
        winner, _ = orch._tally_weighted_votes(votes)
        assert winner == "A"

    async def test_confer_end_to_end(self):
        from parrot.bots.flows.agents import OrchestratorAgent
        from parrot.models.conference import ConferenceResult
        o = OrchestratorAgent(name="orch")
        o.specialist_agents = {
            "data":   _VotingAgent("data", "best-answer", "A", 95),
            "policy": _VotingAgent("policy", "best-answer", "A", 60),
        }
        msg = await o.confer("Q", max_rounds=3)
        assert isinstance(msg.structured_output, ConferenceResult)
        assert msg.content == msg.structured_output.final_answer
        assert msg.structured_output.converged is True
```

---

## Agent Instructions

Read the spec, verify the contract, set status `in-progress`, implement, run tests,
move to `sdd/tasks/completed/`, update the per-spec index to `done`, fill the note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.8)
**Date**: 2026-06-05
**Notes**: Added `_collect_votes` (parallel `agent.ask(structured_output=PeerVote)` with
graceful text-fallback via the new private `_fallback_vote` helper — default confidence
50, keeps own label, warns), `_tally_weighted_votes` (sum confidence per chosen_label,
winner = max via `min(key=(-score, label))` so ties break to the lowest label
deterministically), `_build_conference_result`, and the public `confer()` (init exec
memory → round-0 broadcast → cross-pollinate/vote/tally loop with per-round
`ExecutionMemory` persistence (`vectorize=False`) → convergence break when the winning
agent repeats → `AIMessage(content=final_answer, structured_output=ConferenceResult,
is_structured=True)`). Extended the test module with 8 tests (tally winner, tie-break,
self-vote, no-structured fallback, end-to-end, convergence-stops-early, max_rounds cap
with `until_convergence=False`, and oscillating-winner cap). Full conference suite: 14
passed; ruff clean. `ask()` ReAct loop untouched.
**Deviations from spec**: `_build_conference_result` takes an explicit `winner_label`
(in addition to `winner_agent`) so it can read the winner's aggregated score from
`vote_breakdown` (which is keyed by label) — a minor internal-signature refinement over
the illustrative pattern in the task; behavior matches the spec. `ask(mode="conference")`
exposure remains deferred per this task's explicit out-of-scope note (open question §8).
