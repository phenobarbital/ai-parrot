# TASK-1771: AgentCrew run_* Prompt Passthrough

**Feature**: FEAT-307 — AgentCrew Saved Crews (Execution Persistence & Replay)
**Spec**: `sdd/specs/agentcrew-saved-crews.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1766
**Assigned-to**: unassigned

---

## Context

Each `AgentCrew.run_*` method calls `_save_result()` as a fire-and-forget task,
passing `user_id` and `session_id` via kwargs. This task adds `prompt` and `tenant`
to those kwargs so the saved execution record includes the original query.

Implements spec Module 6.

---

## Scope

- Update each `_save_result()` call site in `AgentCrew` to pass `prompt` and `tenant`:
  - `run_sequential` (line ~1488): pass `query` parameter as `prompt`
  - `run_loop` (line ~1954): pass `query` parameter as `prompt`
  - `run_parallel` (line ~2277): pass a summary or the first task's query as `prompt`
  - `run_flow` (line ~2514): pass `initial_task` parameter as `prompt`
  - `run` (line ~2772): pass `prompt` parameter as `prompt`
  - `ask` (line ~3282): pass `question` parameter as `prompt`
- For `tenant`: extract from `self` if the crew has a reference to `CrewDefinition.tenant`,
  or accept it as a method parameter. Check how `user_id` is currently obtained.
- Write tests verifying prompt is passed through

**NOT in scope**: Modifying `_save_result()` internals (TASK-1766), modifying run_* signatures.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | Add prompt/tenant kwargs to each _save_result call |
| `tests/unit/test_agentcrew_prompt_passthrough.py` | CREATE | Tests verifying prompt forwarding |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.crew import AgentCrew  # crew/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py

# _save_result call sites (current pattern):
# Line ~1487-1494 (run_sequential):
_persist_task = asyncio.get_running_loop().create_task(
    self._save_result(
        result,
        'run_sequential',
        user_id=user_id,
        session_id=session_id
    )
)
self._persist_tasks.add(_persist_task)
_persist_task.add_done_callback(self._persist_tasks.discard)

# Similar pattern at lines ~1954, ~2277, ~2514, ~2772, ~3282

# Method signatures:
async def run_sequential(self, query, ...) -> FlowResult: ...  # line 1172, param: query
async def run_loop(self, query, ...) -> FlowResult: ...  # line 1500, param: query
async def run_parallel(self, tasks, ...) -> FlowResult: ...  # line 1966, param: tasks (List[Dict])
async def run_flow(self, initial_task, ...) -> FlowResult: ...  # line 2289, param: initial_task
async def run(self, prompt, ...) -> AIMessage: ...  # line 2618, param: prompt
async def ask(self, question, ...) -> AIMessage: ...  # line 3108, param: question
```

### Does NOT Exist
- ~~`AgentCrew.tenant` attribute~~ — verify if this exists; the crew may or may not store tenant
- ~~`_save_result(prompt=...)`~~ — not currently passed by any caller

---

## Implementation Notes

### Pattern to Follow
Add `prompt=` and `tenant=` kwargs to each `_save_result()` call:

```python
# In run_sequential:
_persist_task = asyncio.get_running_loop().create_task(
    self._save_result(
        result,
        'run_sequential',
        user_id=user_id,
        session_id=session_id,
        prompt=query,
        tenant=getattr(self, '_tenant', 'global'),
    )
)
```

For `run_parallel`, `tasks` is a `List[Dict[str, Any]]` where each dict has
`agent_id` and `query`. Extract a meaningful prompt — e.g., the first task's
query, or a JSON summary of all queries.

For `tenant`: check if `AgentCrew.__init__` stores the `CrewDefinition` or
its tenant. If not directly available, use `getattr(self, '_tenant', 'global')`
and note this as a minor deviation.

### Key Constraints
- Do NOT modify `run_*` method signatures
- Do NOT modify `_save_result()` internals (TASK-1766 handles that)
- Only add kwargs to existing `_save_result()` calls
- `prompt` should be a string; for `run_parallel`, serialize tasks summary

---

## Acceptance Criteria

- [ ] `run_sequential` passes `prompt=query` to `_save_result()`
- [ ] `run_loop` passes `prompt=query` to `_save_result()`
- [ ] `run_parallel` passes a prompt summary to `_save_result()`
- [ ] `run_flow` passes `prompt=initial_task` to `_save_result()`
- [ ] `run` passes `prompt=prompt` to `_save_result()`
- [ ] `ask` passes `prompt=question` to `_save_result()`
- [ ] `tenant` is passed to all `_save_result()` calls
- [ ] Existing behavior unchanged (prompt/tenant are additive kwargs)
- [ ] Tests verify prompt passthrough
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_agentcrew_prompt_passthrough.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestAgentCrewPromptPassthrough:
    async def test_run_sequential_passes_prompt(self):
        """run_sequential passes query as prompt kwarg to _save_result."""

    async def test_run_loop_passes_prompt(self):
        """run_loop passes query as prompt kwarg."""

    async def test_run_flow_passes_prompt(self):
        """run_flow passes initial_task as prompt kwarg."""

    async def test_run_passes_prompt(self):
        """run passes prompt param as prompt kwarg."""

    async def test_tenant_default_global(self):
        """tenant defaults to 'global' when not set on crew."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1766 must be completed
3. **Verify the Codebase Contract** — read each `_save_result` call site in crew.py
4. **Update status** in `sdd/tasks/index/agentcrew-saved-crews.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1771-agentcrew-prompt-passthrough.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
