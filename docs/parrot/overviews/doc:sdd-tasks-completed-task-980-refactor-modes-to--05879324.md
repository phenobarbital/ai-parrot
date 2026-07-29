---
type: Wiki Overview
title: 'TASK-980: Refactor sequential/loop/parallel modes to use `FlowContext`'
id: doc:sdd-tasks-completed-task-980-refactor-modes-to-flowcontext-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'New signature: `_execute_agent(self, agent, query, session_id, user_id,
  index, **kwargs)`'
relates_to:
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
---

# TASK-980: Refactor sequential/loop/parallel modes to use `FlowContext`

**Feature**: FEAT-143 — Flows Consolidation
**Spec**: `sdd/specs/flows-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-979
**Assigned-to**: unassigned

---

## Context

> Spec Module 5. After TASK-979 moves `AgentCrew` and migrates result models,
> the three non-flow modes (`run_sequential`, `run_loop`, `run_parallel`) still
> use `AgentContext` for execution state tracking. This task replaces all
> `AgentContext` usage with `FlowContext` and refactors `_execute_agent()` to
> accept `**kwargs` directly instead of an `AgentContext` wrapper.
>
> `run_flow()` already uses `FlowContext` correctly and does NOT need changes.

---

## Scope

- Refactor `_execute_agent()` to drop the `context: AgentContext` parameter.
  New signature: `_execute_agent(self, agent, query, session_id, user_id, index, **kwargs)`
  Callers pass `**context.shared_data` instead of an `AgentContext` wrapper.
- In `run_sequential()`:
  - Replace `AgentContext(...)` with `FlowContext(initial_task=query, shared_data={...})`
  - Replace `crew_context.agent_results[agent_id] = result` with
    `context.mark_completed(agent_id, result, response, metadata)`
  - Adapt `_build_context_summary()` to read from `context.results`
- In `run_loop()`:
  - Same pattern as sequential
- In `run_parallel()`:
  - Same pattern as sequential
- Remove the `AgentContext` import from `flows/crew/crew.py`
- Replace all `AgentResult(...)` constructions with `NodeResult(...)` if any
  remain (TASK-979 should have caught most, but some may be in mode-specific code)

**NOT in scope**: Changing `run_flow()` (already uses FlowContext). Modifying
any consumer. Changing the public API of `AgentCrew`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | Refactor 3 modes + `_execute_agent()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# What to remove from flows/crew/crew.py:
from ....tools.agent import AgentContext  # DELETE THIS LINE

# Already available (from TASK-979):
from ..core.context import FlowContext
from ..core.result import NodeResult, NodeExecutionInfo, build_node_metadata, FlowResult
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/orchestration/crew.py:855-906
# Current _execute_agent signature (to be refactored):
async def _execute_agent(
    self,
    agent: Union[BasicAgent, AbstractBot],
    query: str,
    session_id: str,
    user_id: str,
    index: int,
    context: AgentContext,     # ← REMOVE THIS
    model: Optional[str] = None,
    max_tokens: Optional[int] = None
) -> Any:
    # Currently does: **context.shared_data
    # New: accept **kwargs directly

# FlowContext (verified: flows/core/context.py:26-99)
@dataclass
class FlowContext:
    initial_task: str
    results: Dict[str, Any]
    responses: Dict[str, Any]
    node_metadata: Dict[str, NodeExecutionInfo]
    completion_order: List[str]
    errors: Dict[str, Exception]
    active_tasks: Set[str]
    completed_tasks: Set[str]
    shared_data: Dict[str, Any]  # added by TASK-976
    def mark_completed(self, node_id, result=None, response=None, metadata=None): ...
    def mark_failed(self, node_id, error, metadata=None): ...

# AgentContext (to be removed — verified: parrot/tools/agent.py:21-29)
@dataclass
class AgentContext:
    user_id: str
    session_id: str
    original_query: str
    conversation_history: List[ConversationTurn]
    shared_data: Dict[str, Any]
    agent_results: Dict[str, Any]
    metadata: Dict[str, Any]
```

### Does NOT Exist
- ~~`FlowContext.agent_results`~~ — does NOT exist; use `FlowContext.results`
- ~~`FlowContext.original_query`~~ — does NOT exist; use `FlowContext.initial_task`
- ~~`FlowContext.conversation_history`~~ — does NOT exist; not needed

---

## Implementation Notes

### `_execute_agent()` Refactoring

```python
# NEW signature:
async def _execute_agent(
    self,
    agent: Union[BasicAgent, AbstractBot],
    query: str,
    session_id: str,
    user_id: str,
    index: int,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    **kwargs,              # ← replaces context: AgentContext
) -> Any:
    await self._ensure_agent_ready(agent)
    async with self.semaphore:
        if hasattr(agent, 'ask'):
            return await agent.ask(
                question=query,
                session_id=f"{session_id}_agent_{index}",
                user_id=user_id,
                use_conversation_history=True,
                model=model,
                max_tokens=max_tokens,
                **kwargs,  # was **context.shared_data
            )
        # ... same pattern for conversation/invoke
```

### `run_sequential()` Migration Pattern

```python
# OLD:
crew_context = AgentContext(
    user_id=user_id, session_id=session_id,
    original_query=query, conversation_history=[],
    shared_data=kwargs, agent_results={}, metadata={}
)
# ...
response = await self._execute_agent(agent, prompt, session_id, user_id, idx, crew_context, ...)
crew_context.agent_results[agent_id] = result

# NEW:
context = FlowContext(initial_task=query, shared_data=kwargs)
# ...
response = await self._execute_agent(agent, prompt, session_id, user_id, idx, **context.shared_data, ...)
context.mark_completed(agent_id, result=output, response=response, metadata=agent_metadata)
```

### `_build_context_summary()` Adaptation

This method reads agent results to build a context string for the next agent.
Currently reads `crew_context.agent_results`. Must be adapted to read
`context.results` (Dict[str, Any]).

### Key Constraints
- `run_flow()` must NOT be changed — it already uses FlowContext correctly
- The `_execute_agent()` call in `run_flow()` also passes `AgentContext` —
  this call must also be updated to pass `**shared_data` kwargs
- Preserve all return types (`FlowResult`) and public API
- `context.mark_completed()` and `context.mark_failed()` must be called
  for each agent execution (mirrors what `run_flow()` already does)

### References in Codebase
- `parrot/bots/orchestration/crew.py:855-906` — `_execute_agent()` source
- `parrot/bots/orchestration/crew.py:1045-1362` — `run_sequential()` source
- `parrot/bots/orchestration/crew.py:1364-1817` — `run_loop()` source
- `parrot/bots/orchestration/crew.py:1819-2128` — `run_parallel()` source
- `parrot/bots/orchestration/crew.py:2130-2361` — `run_flow()` reference (already uses FlowContext)

---

## Acceptance Criteria

- [ ] No import of `AgentContext` exists in `flows/crew/crew.py`
- [ ] `_execute_agent()` does NOT have a `context: AgentContext` parameter
- [ ] `_execute_agent()` accepts `**kwargs` and passes them through to agent calls
- [ ] `run_sequential()` creates `FlowContext` and calls `mark_completed()`/`mark_failed()`
- [ ] `run_loop()` creates `FlowContext` and calls `mark_completed()`/`mark_failed()`
- [ ] `run_parallel()` creates `FlowContext` and calls `mark_completed()`/`mark_failed()`
- [ ] `run_flow()` call to `_execute_agent()` is updated to use the new signature
- [ ] `_build_context_summary()` reads from `FlowContext.results`
- [ ] All 4 execution modes still return `FlowResult` with correct data

---

## Test Specification

```python
# tests/unit/test_agentcrew_flowcontext.py
import pytest
from unittest.mock import AsyncMock, Mock, patch
from parrot.bots.flows.crew.crew import AgentCrew


class TestNoAgentContextImport:
    def test_no_agent_context_in_source(self):
        import parrot.bots.flows.crew.crew as mod
        source = open(mod.__file__).read()
        assert "from" not in source or "AgentContext" not in source


class TestExecuteAgentSignature:
    def test_no_context_param(self):
        import inspect
        sig = inspect.signature(AgentCrew._execute_agent)
        params = list(sig.parameters.keys())
        assert "context" not in params
        assert "kwargs" in params or any(
            sig.parameters[p].kind == inspect.Parameter.VAR_KEYWORD
            for p in params
        )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-979 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `_execute_agent` signature in
   `flows/crew/crew.py` (it was moved in TASK-979)
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-980-refactor-modes-to-flowcontext.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent (FEAT-143 session)
**Date**: 2026-05-04
**Notes**: Removed `AgentContext` import from `flows/crew/crew.py`. Refactored
`_execute_agent()` to drop `context: AgentContext` parameter and accept `**kwargs`
instead — all three callers now spread `context.shared_data`. Refactored
`run_sequential()`, `run_loop()`, and `run_parallel()` to create `FlowContext`
(instead of `AgentContext`) and call `context.mark_completed()` for each successful
agent execution. Updated `_build_context_summary()` to read from `FlowContext.results`
instead of `AgentContext.agent_results`. In `run_parallel()`, `_run_with_hooks`
captures `context.shared_data` as a default arg snapshot (`_shared=dict(...)`) to
ensure closure safety across concurrent tasks. `run_flow()` unchanged — it already
uses `FlowContext` via `_execute_parallel_agents`.

**Deviations from spec**: none
