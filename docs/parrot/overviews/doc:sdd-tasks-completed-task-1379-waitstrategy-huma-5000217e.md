---
type: Wiki Overview
title: 'TASK-1379: WaitStrategy enum + HumanTool.wait_strategy + SUSPEND branch'
id: doc:sdd-tasks-completed-task-1379-waitstrategy-humantool-suspend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation of FEAT-204 (spec §2 Overview, §3 Module 1). Today `HumanTool._execute`
relates_to:
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.human.tool
  rel: mentions
---

# TASK-1379: WaitStrategy enum + HumanTool.wait_strategy + SUSPEND branch

**Feature**: FEAT-204 — HITL over Stateless Web Request/Response (AgentTalk HTTP)
**Spec**: `sdd/specs/hitl_web.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of FEAT-204 (spec §2 Overview, §3 Module 1). Today `HumanTool._execute`
always **blocks** on `manager.request_human_input()`. This task introduces the
`WaitStrategy` enum and a `wait_strategy` field on `HumanTool` so a stateless web
deployment can choose to *suspend* instead of block — registering the interaction
and raising `HumanInteractionInterrupt` for the HTTP handler to catch.

`wait_strategy` is a **wiring** decision, never exposed to the LLM (same
philosophy `HumanToolInput` applies to consensus/escalation/timeout fields).

---

## Scope

- Add `WaitStrategy(str, Enum)` to `parrot/human/models.py` with members
  `BLOCK = "block"`, `SUSPEND = "suspend"`, `HOT_THEN_SUSPEND = "hot"`.
- Export `WaitStrategy` from `parrot/human/__init__.py`.
- Add a `wait_strategy: WaitStrategy = WaitStrategy.BLOCK` attribute to
  `HumanTool` (`parrot/human/tool.py`). It MUST NOT appear in `HumanToolInput`
  or the tool's LLM-facing args schema.
- In `HumanTool._execute`, branch on `self.wait_strategy`:
  - `BLOCK` (default): existing behaviour, unchanged — await
    `self.manager.request_human_input(...)`.
  - `SUSPEND`: build the rich `HumanInteraction` exactly as the BLOCK path does
    (same `options`/`form_schema`/`severity`/`policy_id`/`timeout`), call
    `await self.manager.request_human_input_async(interaction, channel=...)`,
    then `raise HumanInteractionInterrupt(prompt=<question>, interaction_id=<id>,
    policy_id=<policy_id>)`. Do **not** await a result; do **not** schedule any
    timeout task.
- Unit tests in `packages/ai-parrot/tests/`.

**NOT in scope**: the web/REST tool subclass (TASK-1381); the HTTP handler catch
(TASK-1382); the SuspendedExecution store (TASK-1380). Do not touch
`ai-parrot-server`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/models.py` | MODIFY | Add `WaitStrategy` enum |
| `packages/ai-parrot/src/parrot/human/tool.py` | MODIFY | Add `wait_strategy` field + `SUSPEND` branch in `_execute` |
| `packages/ai-parrot/src/parrot/human/__init__.py` | MODIFY | Export `WaitStrategy` |
| `packages/ai-parrot/tests/test_humantool_wait_strategy.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.core.exceptions import HumanInteractionInterrupt   # core/exceptions.py:12
from parrot.human.models import HumanInteraction, InteractionType  # human/models.py
# After this task: from parrot.human import WaitStrategy
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/human/tool.py
class HumanToolInput(AbstractToolArgsSchema):       # lines 31-141  (DO NOT add wait_strategy here)
    question: str; interaction_type: str = "free_text"
    options: Optional[List[Union[str, Dict[str, Any]]]] = None
    context: Optional[str] = None; timeout: float = 7200.0
    form_schema: Optional[Dict[str, Any]] = None
    default_response: Any = None
    target_humans: Optional[List[str]] = None
    policy_id: Optional[str] = None
    severity: Literal["low","normal","high","critical"] = "normal"
class HumanTool(...):                               # 143-394
    name = "ask_human"; args_schema = HumanToolInput
    async def _execute(self, **kwargs) -> Any: ...  # 247-351; awaits request_human_input() at line 335

# packages/ai-parrot/src/parrot/human/manager.py
async def request_human_input(self, interaction, channel="telegram") -> InteractionResult: ...   # 269  BLOCKS
async def request_human_input_async(self, interaction, channel="telegram") -> str: ...           # 471  returns interaction_id

# packages/ai-parrot/src/parrot/core/exceptions.py
class HumanInteractionInterrupt(ParrotError):       # 12
    def __init__(self, prompt, interaction_id=None, policy_id=None, *a, **k): ...   # 35-41
    # attrs after construction: prompt, interaction_id, policy_id, state, tool_call_id, agent_name, messages
```

### Does NOT Exist
- ~~`WaitStrategy`~~ — you are creating it (do not import before adding).
- ~~`HumanTool.wait_strategy`~~ — you are adding it.
- ~~a `request_human_input_async` that dispatches in pure-web~~ — it skips
  dispatch when no channel is registered (the `if channel in self.channels`
  guard); rely on that, do not add new skip logic.

---

## Implementation Notes

### Pattern to Follow
Read `HumanTool._execute` (tool.py:247-351) and reuse its `HumanInteraction`
construction verbatim for the SUSPEND path — only the *wait* differs. The rich
interaction must be identical so structured types survive the round-trip.

### Key Constraints
- Async throughout; `self.logger` at the suspend point.
- `wait_strategy` excluded from the LLM schema — it is a plain attribute/ctor
  arg, NOT a `HumanToolInput` field.
- SUSPEND must NOT block and must NOT create an asyncio timeout task.
- `HOT_THEN_SUSPEND` may be declared but treated as BLOCK-for-now (reserved for
  live channels); do not implement a poll loop.

### References in Codebase
- `parrot/human/tool.py:247` — `_execute` to branch.
- `parrot/human/manager.py:471` — `request_human_input_async`.
- `parrot/core/exceptions.py:12` — interrupt to raise.

---

## Acceptance Criteria

- [ ] `WaitStrategy` enum exists with `BLOCK`/`SUSPEND`/`HOT_THEN_SUSPEND`.
- [ ] `from parrot.human import WaitStrategy` works.
- [ ] `HumanTool` has `wait_strategy` defaulting to `WaitStrategy.BLOCK`.
- [ ] `wait_strategy` is absent from `HumanToolInput` / the tool args schema.
- [ ] SUSPEND `_execute` calls `request_human_input_async` and raises
      `HumanInteractionInterrupt(interaction_id=...)`; never awaits
      `request_human_input`; never schedules a timeout task.
- [ ] BLOCK path behaviour unchanged.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/test_humantool_wait_strategy.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/human/`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_humantool_wait_strategy.py
import pytest
from parrot.human import WaitStrategy
from parrot.human.tool import HumanTool, HumanToolInput
from parrot.core.exceptions import HumanInteractionInterrupt


def test_wait_strategy_values():
    assert WaitStrategy.BLOCK.value == "block"
    assert WaitStrategy.SUSPEND.value == "suspend"
    assert WaitStrategy.HOT_THEN_SUSPEND.value == "hot"


def test_wait_strategy_not_in_llm_schema():
    assert "wait_strategy" not in HumanToolInput.model_fields


def test_default_wait_strategy_is_block():
    assert HumanTool(manager=None).wait_strategy == WaitStrategy.BLOCK


async def test_suspend_raises_interrupt(monkeypatch):
    """SUSPEND calls request_human_input_async and raises the interrupt."""
    # fake manager whose request_human_input_async returns a known id and
    # whose request_human_input would fail the test if called
    ...
    tool = HumanTool(manager=fake_manager, wait_strategy=WaitStrategy.SUSPEND)
    with pytest.raises(HumanInteractionInterrupt) as exc:
        await tool._execute(question="approve?", interaction_type="approval")
    assert exc.value.interaction_id == "known-id"
    assert fake_manager.async_called and not fake_manager.block_called
```

---

## Agent Instructions

Standard flow: read the spec, verify the contract is still accurate (re-`grep`
`request_human_input_async` and the `HumanInteractionInterrupt` ctor), implement,
test, move this file to `sdd/tasks/completed/`, update
`sdd/tasks/index/hitl_web.json` status to `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
