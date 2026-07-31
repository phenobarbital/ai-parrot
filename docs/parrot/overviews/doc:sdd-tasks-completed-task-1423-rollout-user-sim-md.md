---
type: Wiki Overview
title: 'TASK-1423: Rollout strategies + user simulation (`parrot/eval/rollout.py`)'
id: doc:sdd-tasks-completed-task-1423-rollout-user-sim-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Drives an agent against a task inside a sandbox and produces a `Trajectory`.
  Implements spec §3
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot.eval.models
  rel: mentions
- concept: mod:parrot.eval.sandbox.base
  rel: mentions
---

# TASK-1423: Rollout strategies + user simulation (`parrot/eval/rollout.py`)

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §3 Module 5 (brainstorm §4.2–§4.3)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1415, TASK-1417
**Assigned-to**: unassigned

---

## Context

Drives an agent against a task inside a sandbox and produces a `Trajectory`. Implements spec §3
Module 5: `RolloutStrategy` + `SingleTurnRollout` + `ConversationalRollout`, and the
`UserSimulator`/`LLMUserSimulator` (LLM-driven, τ-bench style).

---

## Scope

- Create `parrot/eval/rollout.py` with:
  - `RolloutStrategy(ABC)` — `async run(bot, task, sandbox) -> Trajectory`.
  - `SingleTurnRollout` — one `bot.ask(...)`; capture `final_output`, `turns`, `latency_ms`, tokens
    if available.
  - `ConversationalRollout(user_sim, max_turns=30)` — loop `bot.conversation(...)` against the
    `UserSimulator` until it returns `None` or `max_turns`.
  - `UserSimulator(ABC)` — `async respond(conversation, scenario) -> str | None`.
  - `LLMUserSimulator(client, system_prompt=None)` — calls `client.ask(...)` (NOT `completion()`),
    temp=0; returns `None` to signal task complete/give up.
- Record `TurnRecord`/`ToolCallRecord` where the agent exposes tool-call info; degrade gracefully if
  not available (leave `tool_calls` empty).
- Export from `parrot/eval/__init__.py`.

**NOT in scope**: the runner loop (TASK-1425), token-cost accounting beyond what the bot/client
return.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/rollout.py` | CREATE | Strategies + user simulators |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export rollout names |
| `packages/ai-parrot/tests/eval/test_rollout.py` | CREATE | Unit tests (mock bot/client) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from abc import ABC, abstractmethod
from parrot.eval.models import EvalTask, Trajectory, TurnRecord, ToolCallRecord   # TASK-1415
from parrot.eval.sandbox.base import Sandbox                                       # TASK-1417
# Type-only to avoid cycles:
# from parrot.bots.abstract import AbstractBot     # bots/abstract.py:155
# from parrot.clients.base import AbstractClient   # clients/base.py:242
```

### Existing Signatures to Use
```python
# bots/abstract.py
class AbstractBot(...):                  # line 155
    async def ask(self, ...): ...        # line 3660 → AIMessage
    async def conversation(self, ...): ...  # line 3107 → AIMessage
# clients/base.py
class AbstractClient(EventEmitterMixin, ABC):   # line 242
    async def ask(self, ...): ...        # line 1497 (abstract)
```
> Inspect the exact `ask()` / `conversation()` parameters in `bots/abstract.py` before calling — pass
> the task input as the message; do not invent kwargs.

### Does NOT Exist
- ~~`AbstractClient.completion()` / `.stream()` / `.embed()`~~ — use `ask()` / `ask_stream()` only.
- ~~`AbstractBot.run()` as the canonical entrypoint~~ — use `ask()` / `conversation()`.

---

## Implementation Notes

### Key Constraints
- Async throughout; time the rollout with `time.perf_counter()` → `latency_ms`.
- `LLMUserSimulator` temp=0 for reproducibility; the scenario goal constrains it; `None` ends the loop.
- Be defensive about the bot's return shape (`AIMessage`) — read `bots/abstract.py` for the content
  accessor before extracting text.

### References in Codebase
- `parrot/bots/abstract.py` — `ask`, `conversation`, `AIMessage` shape.
- `parrot/clients/base.py:1497` — `ask` signature for the simulator.

---

## Acceptance Criteria

- [ ] `from parrot.eval import SingleTurnRollout, ConversationalRollout, LLMUserSimulator` resolves.
- [ ] `SingleTurnRollout.run` with a mock bot returns a `Trajectory` with `final_output` and
      `latency_ms > 0`.
- [ ] `ConversationalRollout` stops when the simulator returns `None` and respects `max_turns`.
- [ ] `LLMUserSimulator.respond` calls `client.ask` (asserted via mock).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_rollout.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/rollout.py`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock
from parrot.eval import SingleTurnRollout
from parrot.eval.models import EvalTask
from parrot.eval.sandbox.base import NoopSandbox

async def test_single_turn_records_trajectory():
    bot = AsyncMock()
    bot.ask.return_value = type("M", (), {"content": "done"})()
    task = EvalTask(task_id="t", inputs={"query": "hi"})
    tr = await SingleTurnRollout().run(bot, task, NoopSandbox())
    assert tr.task_id == "t" and tr.final_output is not None
    bot.ask.assert_awaited()
```

---

## Agent Instructions

Standard SDD flow: read `ask`/`conversation` signatures first, verify the contract, set index
`in-progress`, implement, run tests + ruff, move to `completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
