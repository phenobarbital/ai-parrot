---
type: Wiki Overview
title: 'TASK-1771: AgentCrew run_* Prompt Passthrough'
id: doc:sdd-tasks-completed-task-1771-agentcrew-prompt-passthrough-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Each `AgentCrew.run_*` method calls `_save_result()` as a fire-and-forget
  task,
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
---

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

# _save_result call sites (current pattern, VERIFIED at these exact line numbers):
# Lines 1487-1494 (run_sequential):
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

# Same pattern at lines 1954 (run_loop), 2277 (run_parallel),
# 2514 (run_flow), 2772 (run), 3282 (ask)

# Method signatures (VERIFIED — two entries corrected from the original
# contract, which had stale param names for run_loop and run):
async def run_sequential(self, query: str, ...) -> FlowResult: ...  # line 1172, param: query
async def run_loop(self, initial_task: str, condition: str, ...) -> FlowResult: ...  # line 1500, param: initial_task (NOT "query" — corrected)
async def run_parallel(self, tasks: List[Dict[str, Any]], ...) -> FlowResult: ...  # line 1966, param: tasks (each dict has 'agent_id'/'query'); a local var `original_query = tasks[0]['query'] if tasks else ""` is already computed at line 2007
async def run_flow(self, initial_task: str, ...) -> FlowResult: ...  # line 2289, param: initial_task
async def run(self, task: Union[str, Dict[str, str]], ...) -> AIMessage: ...  # line 2618, param: task (NOT "prompt" — corrected; str or {agent_id: prompt} dict)
async def ask(self, question: str, ...) -> AIMessage: ...  # line 3108, param: question
```

### Does NOT Exist
- ~~`AgentCrew.tenant` attribute~~ — CONFIRMED does not exist. `AgentCrew.__init__`
  (line 132) stores no reference to `CrewDefinition` or its `tenant` field, and
  `from_definition()` (line 346) does not persist `crew_def.tenant` onto the
  instance either, even though `CrewDefinition.tenant` itself exists
  (`parrot/models/crew_definition.py:113`). Use `getattr(self, '_tenant', 'global')`
  per the Implementation Notes below — documented as a minor deviation.
- ~~`_save_result(prompt=...)`~~ — not currently passed by any caller
- ~~`run_loop(query=...)`~~ — parameter is named `initial_task`, not `query`
- ~~`run(prompt=...)`~~ — parameter is named `task`, not `prompt`

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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Added `prompt=` and `tenant=getattr(self, '_tenant', 'global')` kwargs to
all six `_save_result()` call sites in `crew.py` (`run_sequential` → `prompt=query`;
`run_loop` → `prompt=initial_task`; `run_parallel` → `prompt=original_query`, reusing
the local var already computed at line 2014 for `ExecutionMemory`; `run_flow` →
`prompt=initial_task`; `run` → `prompt=task if isinstance(task, str) else str(task)`;
`ask` → `prompt=question`). Confirmed via `grep`/`Read` that `AgentCrew` has no
`tenant`/`CrewDefinition` reference anywhere (`__init__` nor `from_definition()`),
so used `getattr(self, '_tenant', 'global')` exactly as the task's own fallback
guidance prescribes.

Corrected two **stale entries in the task's own Codebase Contract** before
implementing (per the anti-hallucination protocol): `run_loop`'s persisted-query
parameter is `initial_task`, not `query`; `run`'s parameter is `task`
(`Union[str, Dict[str, str]]`), not `prompt`. Both corrections are recorded in the
task file's contract section.

Created `tests/unit/test_agentcrew_prompt_passthrough.py` — driven via genuine
`run_sequential`/`run_loop`/`run_flow`/`run_parallel`/`run`/`ask` execution against
a minimal fake agent (`MagicMock` with working async `.ask()`, satisfying the
`AgentLike` structural protocol) rather than mocking `_save_result`'s call site
directly, so the tests exercise the real kwarg-forwarding code path end-to-end.
9/9 tests pass. `ruff check` clean. No regressions in
`tests/bots/flows/core/storage/` (`-k flows` subset: 4/4 pass; the `orchestration`-
prefixed subset fails for a pre-existing, unrelated reason — `parrot.bots.orchestration`
was removed in FEAT-143/196, confirmed failing identically on `dev` before this task).

**Deviations from spec / discovered pre-existing bugs (flagging for follow-up, NOT
fixed here — out of scope for this task)**:
1. **`run_loop()` is currently broken for any crew.** It unconditionally does
   `node.fsm = AgentTaskMachine(agent_name=node.agent.name)` every iteration
   (`crew.py:1625`), but `CrewAgentNode` (and its `Node` base) is a frozen Pydantic
   model (`ConfigDict(frozen=True)`, `flows/core/node.py`). This raises a
   `pydantic_core.ValidationError` (`Instance is frozen`) for every agent in
   `workflow_graph`, on the very first iteration, for ANY crew — not something
   introduced by this task. Worked around in the test by clearing
   `crew.workflow_graph = {}` before calling `run_loop()` (the method's own
   `if node: ...` guards already treat a missing node as "no FSM tracking for
   this run," which cleanly isolates the prompt-passthrough behavior under test
   from this unrelated bug). Recommend a dedicated bug-fix task using the
   frozen-safe `object.__setattr__` escape hatch documented at
   `flows/core/node.py:227`.
2. **`run()` is currently broken for any crew.** It does
   `parallel_result['results']` (`crew.py:2726`) after calling
   `self.run_parallel(...)`, but `FlowResult.__getitem__`'s mapping
   (`flows/core/result.py:421-445`) has no `"results"` key — only `"node_results"`/
   `"agent_results"` — so this always raises `KeyError('results')`, again for ANY
   crew, unrelated to this task. Worked around in the test by monkeypatching
   `crew.run_parallel` to return a plain dict (which trivially supports
   `['results']`), isolating the `prompt=task`/`tenant=` forwarding under test.
   Recommend a follow-up fix changing `crew.py:2726` to use `'node_results'` (or
   another correct key) and adding regression coverage for `run()` end-to-end.
