---
type: Wiki Overview
title: 'TASK-1476: Broadcast round + anonymized peer-context helpers'
id: doc:sdd-tasks-completed-task-1476-broadcast-and-anonymous-peer-block-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 2 of the spec (§2 Component Diagram, §3 Module 2). Provides
  the two
relates_to:
- concept: mod:parrot.bots.flows.agents
  rel: mentions
- concept: mod:parrot.models.conference
  rel: mentions
---

# TASK-1476: Broadcast round + anonymized peer-context helpers

**Feature**: FEAT-223 — Multi-Party Conferencing for OrchestratorAgent
**Spec**: `sdd/specs/orchestratoragent-multiparty.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1475
**Assigned-to**: unassigned

---

## Context

Implements Module 2 of the spec (§2 Component Diagram, §3 Module 2). Provides the two
deterministic building blocks the conference loop needs: a parallel **broadcast** of one
question to all selected specialists, and an **anonymized** peer-answer block
("Answer A / Answer B / …") with an internal `label_to_agent` map so the LLM never sees
who authored which answer (reduces authority bias).

---

## Scope

- Add private helper `async def _broadcast_round(self, question, agents=None) -> Dict[str, str]`
  to `OrchestratorAgent`: fan-out via `asyncio.gather` over the selected
  `self.specialist_agents`, returning `{agent_name: answer_text}`.
- Add private helper
  `def _build_anonymous_peer_block(self, answers: Dict[str, str]) -> tuple[str, Dict[str, str]]`:
  produces `(peer_block_text, label_to_agent)` where labels are A, B, C…, each answer is
  truncated to 2000 chars, and NO agent name/role appears in `peer_block_text`.
- Resolve the `agents` argument: `None` → all specialists; otherwise the named subset
  (validate names against `self.specialist_agents`).
- Write unit tests for both helpers.

**NOT in scope**: voting, tally, convergence, the public `confer()` method
(TASK-1477); the data models (TASK-1475).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py` | MODIFY | Add `_broadcast_round`, `_build_anonymous_peer_block`, `_resolve_agents` |
| `packages/ai-parrot/tests/test_orchestrator_conference.py` | CREATE | Unit tests for the helpers (extended in TASK-1477/1478) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-05. Monorepo paths under `packages/ai-parrot/src/`.

### Verified Imports
```python
import asyncio  # stdlib
from typing import Dict, List, Optional, Tuple
from parrot.models.conference import PeerVote  # created in TASK-1475
```

### Existing Signatures to Use
```python
# parrot/bots/flows/agents/orchestrator.py
class OrchestratorAgent(BasicAgent):                                  # L20
    specialist_agents: Dict[str, Union[BasicAgent, AbstractBot]]      # L38  (key = agent.name)
    def _init_execution_memory(self, question: str)                  # L199
    def list_agents(self) -> List[str]                               # L326
    async def ask(self, question: str, **kwargs) -> AIMessage        # L285  (DO NOT modify)

# Each specialist exposes (one of), see parrot/tools/agent.py:_execute L220-246:
#   async def conversation(...) -> AIMessage|AgentResponse
#   async def ask(question, ..., structured_output=None, **kwargs) -> AIMessage   # parrot/bots/base.py:718
#   async def invoke(...) -> ...
# Answer text extraction precedent (parrot/tools/agent.py L260-267): prefer
#   response.content; fallback response.output; fallback str(response).

# Truncation precedent (anonymized block mirrors this, but WITHOUT author names):
# parrot/tools/agent.py:_build_cross_pollination_context L313 (max_result_length=2000)
```

### Does NOT Exist
- ~~`OrchestratorAgent._broadcast_round` / `._build_anonymous_peer_block`~~ — create them.
- ~~An anonymous peer block built-in~~ — `_build_cross_pollination_context` is **attributed**
  (uses `agent_result.agent_name`, L347) and sequential; do NOT reuse it as-is.
- ~~`OrchestratorAgent.confer`~~ — added in TASK-1477.

---

## Implementation Notes

### Pattern to Follow
```python
async def _broadcast_round(self, question: str, agents=None) -> Dict[str, str]:
    names = self._resolve_agents(agents)
    async def _one(name: str) -> tuple[str, str]:
        agent = self.specialist_agents[name]
        resp = await agent.ask(question=question, use_conversation_history=False)
        text = getattr(resp, "content", None) or getattr(resp, "output", None) or str(resp)
        return name, text
    pairs = await asyncio.gather(*[_one(n) for n in names])
    return dict(pairs)

def _build_anonymous_peer_block(self, answers):
    labels = [chr(ord("A") + i) for i in range(len(answers))]
    label_to_agent, lines = {}, ["## Peer answers (anonymous)\n"]
    for label, (agent_name, text) in zip(labels, answers.items()):
        label_to_agent[label] = agent_name
        if len(text) > 2000:
            text = text[:2000] + "\n... [truncated]"
        lines.append(f"### Answer {label}\n{text}\n")
    return "\n".join(lines), label_to_agent
```

### Key Constraints
- Async-first: use `asyncio.gather`, never sequential awaits in a loop for the fan-out.
- The peer block text MUST NOT contain agent names, roles, or goals.
- Use `self.logger` for round/agent diagnostics.
- Prefer calling each specialist's `ask()`; if a specialist lacks `ask`, fall back to
  `conversation`/`invoke` like `AgentTool._execute` does.

### References in Codebase
- `parrot/bots/flows/crew/crew.py:1966` `run_parallel` — `asyncio.gather` fan-out pattern.
- `parrot/tools/agent.py:313` — truncation + block formatting (attributed; adapt to anonymous).
- `parrot/tools/agent.py:260-267` — response-content extraction precedent.

---

## Acceptance Criteria

- [ ] `_broadcast_round` calls every selected specialist concurrently and returns one
      answer string per agent.
- [ ] `_build_anonymous_peer_block` returns labels A/B/C…, a correct `label_to_agent`
      map, and text that contains NO agent name.
- [ ] Each answer in the block is truncated to ≤ 2000 chars.
- [ ] `agents=None` selects all specialists; a named subset selects only those; unknown
      name raises a clear `ValueError`.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/test_orchestrator_conference.py -v`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_orchestrator_conference.py
import pytest
from parrot.bots.flows.agents import OrchestratorAgent


class _FakeAgent:
    def __init__(self, name, answer):
        self.name = name
        self._answer = answer
    async def ask(self, question, **kw):
        class _R:  # minimal AIMessage-like
            content = self._answer
        return _R()


@pytest.fixture
def orch():
    o = OrchestratorAgent(name="orch")
    o.specialist_agents = {
        "data": _FakeAgent("data", "answer-from-data"),
        "policy": _FakeAgent("policy", "answer-from-policy"),
    }
    return o


class TestBroadcastAndBlock:
    async def test_broadcast_parallel(self, orch):
        out = await orch._broadcast_round("Q")
        assert set(out) == {"data", "policy"}
        assert out["data"] == "answer-from-data"

    def test_anonymous_block(self, orch):
        block, mapping = orch._build_anonymous_peer_block(
            {"data": "answer-from-data", "policy": "answer-from-policy"}
        )
        assert "data" not in block and "policy" not in block   # no author names
        assert set(mapping) == {"A", "B"}

    def test_truncation(self, orch):
        block, _ = orch._build_anonymous_peer_block({"data": "x" * 5000})
        assert "[truncated]" in block
```

---

## Agent Instructions

Read the spec, verify the contract, set status `in-progress`, implement, run tests,
move to `sdd/tasks/completed/`, update the per-spec index to `done`, fill the note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.8)
**Date**: 2026-06-05
**Notes**: Added `_resolve_agents` (None=all, named subset validated, unknown →
`ValueError`), `_broadcast_round` (parallel `asyncio.gather` fan-out → `{agent: text}`),
and `_build_anonymous_peer_block` (labels A/B/C…, `label_to_agent` map, per-answer
truncation to 2000 chars, NO author names in the text). Two private helpers were
factored out to serve the task-required behavior: `_invoke_specialist` (prefer `ask`,
fall back to `conversation`/`invoke` like `AgentTool._execute`, dropping
`structured_output` for non-`ask` paths) and `_extract_answer_text` (content→output→str
extraction precedent). New test module `test_orchestrator_conference.py` (6 tests):
broadcast all/subset, anonymity, truncation, resolve unknown/none. All pass; ruff clean.
**Deviations from spec**: (1) The task's literal `test_anonymous_block` sample answers
("answer-from-data") embed the agent name as a substring, making `"data" not in block`
impossible for any correct block that includes answer text; I used answer text that does
not embed the agent name so the anonymity assertion is meaningful (intent preserved).
(2) The bot test conftest stubs the heavy `BasicAgent` base (no `logger`), so the
fixture sets `o.logger` — production `BasicAgent` provides `self.logger`; this mirrors
the existing `test_orchestrator_agent.py` pattern.
