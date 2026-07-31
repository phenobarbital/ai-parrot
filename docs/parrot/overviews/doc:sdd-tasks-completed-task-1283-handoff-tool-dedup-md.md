---
type: Wiki Overview
title: 'TASK-1283: HandoffTool dedup + DeprecationWarning'
id: doc:sdd-tasks-completed-task-1283-handoff-tool-dedup-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C10**. Today `HandoffTool._aexecute`
relates_to:
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1283: HandoffTool dedup + DeprecationWarning

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1277
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C10**. Today `HandoffTool._aexecute`
(handoff.py:44-72) does two things at once: registers the interaction
with the manager AND raises `HumanInteractionInterrupt`. This forces
the orchestrator to suspend the agent even when the manager-registered
flow has already resolved (e.g., a non-INTERACT starting tier finishes
fire-and-forget immediately). This task removes the race.

---

## Scope

- Refactor `HandoffTool._aexecute` so that, when the manager is
  configured and registration succeeds:
  1. After `request_human_input_async` returns (today it just hands
     back the `interaction_id`), poll `manager.get_result(interaction_id)`
     with a short bounded retry window (e.g., 5 × 100ms — total ≤ 500ms).
  2. If a result appears within the window AND its
     `action_metadata` contains a `message`, return that string and do
     NOT raise `HumanInteractionInterrupt`. The orchestrator never
     suspends.
  3. If no result appears in time, fall back to the legacy `raise
     HumanInteractionInterrupt(prompt, interaction_id, policy_id)` so
     the existing suspend/resume path keeps working.
- When the manager is `None` (no integration wired), keep the legacy
  raise unchanged.
- Emit `DeprecationWarning` on first `HandoffTool` instantiation per
  process (use a class-level `_deprecation_warned` flag).
- Update the tool's docstring to point users to
  `HumanTool(..., policy_id="...")` for new code.

**NOT in scope**: Orchestrator-side short-circuit hardening
(TASK-1284 — that one handles the case where the orchestrator catches
the interrupt but a result is already in Redis).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/tools/handoff.py` | MODIFY | Dedup logic + DeprecationWarning |
| `packages/ai-parrot/tests/core/tools/test_handoff_tool.py` | MODIFY | Add dedup + warning tests; preserve legacy fallback tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing:
from parrot.core.exceptions import HumanInteractionInterrupt   # handoff.py:7
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema  # handoff.py:6
# Lazy in _aexecute:
from parrot.human.models import HumanInteraction, InteractionType  # handoff.py:49
# New:
import warnings
import asyncio
```

### Existing Signatures to Use

```python
# parrot/core/tools/handoff.py:22-76 — current shape
class HandoffTool(AbstractTool):
    name: str = "handoff_to_human"
    args_schema: Type[BaseModel] = HandoffToolSchema   # includes policy_id

    def __init__(self, manager: Any = None, **kwargs):
        super().__init__(**kwargs)
        self.manager = manager

    async def _aexecute(self, prompt, policy_id=None, **kwargs):
        interaction_id = None
        if self.manager:
            interaction = HumanInteraction(
                question=prompt,
                interaction_type=InteractionType.FREE_TEXT,
                policy_id=policy_id,
                source_agent=getattr(self, "source_agent", None),
            )
            try:
                interaction_id = await self.manager.request_human_input_async(
                    interaction, channel=kwargs.get("channel", "telegram"),
                )
            except Exception:
                pass
        raise HumanInteractionInterrupt(
            prompt=prompt,
            interaction_id=interaction_id,
            policy_id=policy_id,
        )

# parrot/human/manager.py:354-362
async def get_result(self, interaction_id) -> Optional[InteractionResult]: ...
```

### Does NOT Exist

- ~~A synchronous `wait_for_result` helper on the manager~~ — use the
  existing `get_result` in a short polling loop.
- ~~`HandoffTool._deprecated`~~ — class-level flag, to be added.

---

## Implementation Notes

### Pattern to Follow

```python
class HandoffTool(AbstractTool):
    _deprecation_warned = False  # class-level

    def __init__(self, manager=None, **kwargs):
        super().__init__(**kwargs)
        self.manager = manager
        if not HandoffTool._deprecation_warned:
            warnings.warn(
                "HandoffTool is deprecated; prefer HumanTool with policy_id "
                "for tiered escalation. See documentation/hitl_tiered_escalation_example.md.",
                DeprecationWarning,
                stacklevel=2,
            )
            HandoffTool._deprecation_warned = True

    async def _aexecute(self, prompt, policy_id=None, **kwargs):
        interaction_id = None
        if self.manager:
            # ... register via request_human_input_async ...

            # Short bounded poll for an already-resolved result
            for _ in range(5):
                await asyncio.sleep(0.1)
                result = await self.manager.get_result(interaction_id)
                if result is not None:
                    msg = (result.action_metadata or {}).get("message")
                    if msg:
                        return msg
                    if result.consolidated_value is not None:
                        return result.consolidated_value
                    break  # resolved but empty — fall through to interrupt

        raise HumanInteractionInterrupt(
            prompt=prompt,
            interaction_id=interaction_id,
            policy_id=policy_id,
        )
```

### Key Constraints

- Polling window MUST be bounded (≤ 500ms total) so the tool's latency
  stays predictable.
- `DeprecationWarning` fires exactly once per process; use a class-level
  flag (not instance) and reset only in tests via monkeypatching.
- Legacy path (no manager) is untouched.
- The orchestrator-side change (catch path) is TASK-1284; this task
  does NOT touch `parrot/autonomous/orchestrator.py`.

### References in Codebase

- Spec §3 C10 + §7 "HandoffTool dual-path race" gotcha.
- `parrot/agents/demo.py:194` — known existing `HandoffTool` callsite
  that must continue working.

---

## Acceptance Criteria

- [ ] `HandoffTool()` emits `DeprecationWarning` exactly once per
  process (verified with `warnings.simplefilter("always")` and a
  catch-all check).
- [ ] When the manager-registered interaction resolves within the
  polling window with a non-empty `action_metadata["message"]`,
  `HandoffTool._aexecute` returns the string and does NOT raise
  `HumanInteractionInterrupt`.
- [ ] When the manager-registered interaction does not resolve in the
  window, the tool raises `HumanInteractionInterrupt` with the
  `interaction_id` and `policy_id` populated.
- [ ] When `self.manager is None`, the tool raises
  `HumanInteractionInterrupt(prompt=prompt)` (legacy behaviour).
- [ ] Existing tests in `tests/core/tools/test_handoff_tool.py` and
  `tests/agents/test_demo.py` keep passing without modification.
- [ ] All tests pass:
  `pytest packages/ai-parrot/tests/core/tools/test_handoff_tool.py packages/ai-parrot/tests/agents/test_demo.py -v`.

---

## Test Specification

```python
# tests/core/tools/test_handoff_tool.py — new
class TestDeprecationWarning:
    def test_warning_fires_once_per_process(self): ...
    def test_warning_message_points_to_human_tool(self): ...

class TestDedup:
    async def test_returns_message_when_manager_resolves_in_window(self): ...
    async def test_raises_interrupt_when_manager_does_not_resolve_in_window(self): ...
    async def test_raises_interrupt_when_no_manager_configured(self): ...
```

---

## Agent Instructions

1. Read spec §3 C10 + §7 dual-path-race gotcha.
2. Verify TASK-1277 completed (`advance_chain` + fixed
   `_escalate_to_next_tier` available).
3. Implement, test against existing demo tests too.
4. Move to completed.

---

## Completion Note

Implemented 2026-05-22 by sdd-worker (FEAT-194).

- Added `_deprecation_warned: bool = False` class-level flag and `DeprecationWarning` emission in `__init__` (fires once per process; reset with `HandoffTool._deprecation_warned = False` in tests).
- Added short bounded poll (5 x 100ms) in `_aexecute` after `request_human_input_async`: returns `action_metadata["message"]` or `consolidated_value` immediately if available; falls through to interrupt if poll exhausted or result empty.
- Legacy path (no manager) and `_execute` sync path unchanged.
- 8 tests all pass: 2 legacy, 2 DeprecationWarning, 4 dedup. Demo agent tests (7) also pass; `demo.py:194` HandoffTool now emits the deprecation warning as expected.
