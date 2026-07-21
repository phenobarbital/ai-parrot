---
type: Wiki Overview
title: 'TASK-918: Transitions — FlowTransition Dataclass'
id: doc:sdd-tasks-completed-task-918-flow-primitives-transition-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extracts `FlowTransition` from `parrot.bots.flow.fsm` into the shared
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.fsm
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.transition
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
---

# TASK-918: Transitions — FlowTransition Dataclass

**Feature**: FEAT-134 — Flow Primitives — Shared Core for AgentCrew & AgentsFlow
**Spec**: `sdd/specs/flow-primitives.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-913, TASK-914, TASK-915
**Assigned-to**: unassigned

---

## Context

Extracts `FlowTransition` from `parrot.bots.flow.fsm` into the shared
`parrot.bots.flows.core.transition` module. `FlowTransition` defines
conditional edges between nodes with predicates, priority, and prompt builders.

Implements Spec §3 Module 6.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/core/transition.py`:
  - `FlowTransition` dataclass — extracted from `parrot.bots.flow.fsm:115-194`.
    Fields: `source`, `targets`, `condition`, `instruction`, `prompt_builder`,
    `predicate`, `priority`, `metadata`.
    Methods: `should_activate()`, `build_prompt()`.
  - Uses `TransitionCondition` from `core.fsm` (TASK-914).
  - Uses `NodeExecutionInfo` from `core.result` (TASK-915) for `metadata` field.
- Write unit tests.

**NOT in scope**: `FlowNode` (engine-specific), modifying existing `fsm.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/transition.py` | CREATE | FlowTransition |
| `packages/ai-parrot/tests/test_flow_primitives/test_transition.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-914:
from parrot.bots.flows.core.fsm import TransitionCondition

# From TASK-913:
from parrot.bots.flows.core.types import PromptBuilder, DependencyResults

# From TASK-915:
from parrot.bots.flows.core.result import NodeExecutionInfo
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flow/fsm.py:115-194
@dataclass
class FlowTransition:
    source: str
    targets: Set[str]
    condition: TransitionCondition = TransitionCondition.ON_SUCCESS
    instruction: Optional[str] = None
    prompt_builder: Optional[PromptBuilder] = None
    predicate: Optional[Callable[[Any], Union[bool, Awaitable[bool]]]] = None
    priority: int = 0
    metadata: Optional[AgentExecutionInfo] = None

    async def should_activate(self, result: Any, error: Optional[Exception] = None) -> bool:
        # ALWAYS → True
        # ON_SUCCESS → error is None
        # ON_ERROR → error is not None
        # ON_CONDITION with predicate → call predicate (handles async)
        # else → False

    async def build_prompt(self, context: AgentContext, dependencies: DependencyResults) -> str:
        # 1. Use prompt_builder if set (handle async)
        # 2. Use instruction if set
        # 3. Default: "Task: {context.original_query}" + dependency context
```

### Does NOT Exist
- ~~`parrot.bots.flows.core.transition`~~ — does not exist yet

---

## Implementation Notes

### Key Constraints
- `metadata` field type changes from `Optional[AgentExecutionInfo]` to
  `Optional[NodeExecutionInfo]`.
- `build_prompt()` first argument is `Any` (not `AgentContext`) in the shared
  version — it expects an object with `original_query` attribute but does not
  import `AgentContext` to avoid coupling.
- `should_activate()` must handle both sync and async predicates via
  `asyncio.iscoroutine()`.
- Preserve exact activation semantics from the existing implementation.

---

## Acceptance Criteria

- [ ] `FlowTransition` dataclass with all fields
- [ ] `should_activate()` handles ALWAYS, ON_SUCCESS, ON_ERROR, ON_CONDITION correctly
- [ ] `build_prompt()` supports prompt_builder, instruction, and default fallback
- [ ] `metadata` field uses `NodeExecutionInfo` (not `AgentExecutionInfo`)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_flow_primitives/test_transition.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_transition.py
import pytest
from parrot.bots.flows.core.transition import FlowTransition
from parrot.bots.flows.core.fsm import TransitionCondition


class TestTransitionShouldActivate:
    @pytest.mark.asyncio
    async def test_always_activates(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ALWAYS)
        assert await t.should_activate(result="ok") is True

    @pytest.mark.asyncio
    async def test_on_success_no_error(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ON_SUCCESS)
        assert await t.should_activate(result="ok", error=None) is True

    @pytest.mark.asyncio
    async def test_on_success_with_error(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ON_SUCCESS)
        assert await t.should_activate(result=None, error=Exception("fail")) is False

    @pytest.mark.asyncio
    async def test_on_error_with_error(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ON_ERROR)
        assert await t.should_activate(result=None, error=Exception("fail")) is True

    @pytest.mark.asyncio
    async def test_on_condition_with_sync_predicate(self):
        t = FlowTransition(
            source="a", targets={"b"},
            condition=TransitionCondition.ON_CONDITION,
            predicate=lambda r: "yes" in str(r)
        )
        assert await t.should_activate(result="yes please") is True
        assert await t.should_activate(result="no thanks") is False

    @pytest.mark.asyncio
    async def test_on_condition_with_async_predicate(self):
        async def pred(r):
            return r > 10
        t = FlowTransition(
            source="a", targets={"b"},
            condition=TransitionCondition.ON_CONDITION,
            predicate=pred
        )
        assert await t.should_activate(result=20) is True
        assert await t.should_activate(result=5) is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 6
2. **Check dependencies** — TASK-913, TASK-914, TASK-915 must be completed
3. **Verify** existing `FlowTransition` in `packages/ai-parrot/src/parrot/bots/flow/fsm.py:115-194`
4. **Implement** following the exact same activation and prompt-building logic

---

## Completion Note

Completed 2026-04-29. Created `parrot/bots/flows/core/transition.py` with `FlowTransition` dataclass:
- Fields: `source`, `targets: Set[str]`, `condition: TransitionCondition`, `instruction`, `prompt_builder`, `predicate`, `priority: int`, `metadata: Optional[NodeExecutionInfo]`.
- `should_activate()`: ALWAYS/ON_SUCCESS/ON_ERROR/ON_CONDITION logic preserved exactly; handles sync and async predicates.
- `build_prompt()`: priority order (prompt_builder > instruction > default fallback); accepts `Any` context via duck-typing.
All 20 unit tests pass.
