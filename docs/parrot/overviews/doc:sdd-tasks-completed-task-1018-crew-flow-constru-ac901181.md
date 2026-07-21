---
type: Wiki Overview
title: 'TASK-1018: Wire `persist_results` / `result_storage` into AgentCrew & AgentsFlow
  + lifecycle'
id: doc:sdd-tasks-completed-task-1018-crew-flow-constructor-wiring-and-lifecycle-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wires the new constructor parameters (`persist_results`,
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.persistence
  rel: mentions
---

# TASK-1018: Wire `persist_results` / `result_storage` into AgentCrew & AgentsFlow + lifecycle

**Feature**: FEAT-147 — Crew Result Storage Backends
**Spec**: `sdd/specs/crew-result-storage-backends.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1017
**Assigned-to**: unassigned

---

## Context

Wires the new constructor parameters (`persist_results`,
`result_storage`) into the three host classes that consume the rewritten
`PersistenceMixin`, registers the four mixin-owned attributes
(`_persist_results`, `_result_storage_arg`, `_result_storage`,
`_persist_tasks`), and updates every `_save_result(...)` call site so the
scheduled `asyncio.Task` is added to `self._persist_tasks` (with a
discard-on-done callback) instead of being silently dropped.

There are **three host classes**: two duplicated `AgentCrew` instances
(`parrot/bots/orchestration/crew.py` and `parrot/bots/flows/crew/crew.py`)
plus `AgentsFlow` in `parrot/bots/flow/fsm.py`. All three must stay in
lockstep — that duplication is pre-existing tech debt and out-of-scope
for FEAT-147 beyond keeping it consistent.

Implements spec §2 "Lifecycle & Cleanup" and §3 Module 6.

---

## Scope

For each of the three host classes:

- Add `persist_results: bool = True` and
  `result_storage: Union[str, ResultStorage, None] = None` to `__init__`.
- Initialise four attributes in `__init__`:
  - `self._persist_results = persist_results`
  - `self._result_storage_arg = result_storage`
  - `self._result_storage: Optional[ResultStorage] = (
      result_storage if isinstance(result_storage, ResultStorage) else None
    )`
  - `self._persist_tasks: set[asyncio.Task] = set()`
- Update every `_save_result(...)` call site so the scheduled task is
  registered. Replace:
  ```python
  asyncio.get_running_loop().create_task(
      self._save_result(result, "run_X", user_id=user_id, session_id=session_id)
  )
  ```
  with:
  ```python
  task = asyncio.get_running_loop().create_task(
      self._save_result(result, "run_X", user_id=user_id, session_id=session_id)
  )
  self._persist_tasks.add(task)
  task.add_done_callback(self._persist_tasks.discard)
  ```
- The mixin's `aclose()`, `__aenter__`, and `__aexit__` are inherited
  from `PersistenceMixin` (already implemented in TASK-1017) — no
  override needed in the host classes.
- Add unit tests covering: opt-out skips connection, env-var fallback,
  `async with` protocol releases the connection, in-flight task tracking.

**NOT in scope**: Refactoring the duplicated `AgentCrew` into a single
class, refactoring `_save_result` call patterns beyond the
task-registration line, touching the synthesis or memory mixins.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/orchestration/crew.py` | MODIFY | New constructor params + 6 call-site updates (lines 1355, 1810, 2121, 2354, 2610, 3118 per spec §6). |
| `parrot/bots/flows/crew/crew.py` | MODIFY | Same new constructor params + 6 call-site updates (lines 1292, 1753, 2071, 2303, 2559, 3067 per spec §6). |
| `parrot/bots/flow/fsm.py` | MODIFY | New constructor params + 1 call-site update (line 944 per spec §6). |
| `tests/bots/flows/core/storage/test_agentcrew_lifecycle.py` | CREATE | Integration-flavoured unit tests covering both `AgentCrew` copies. |
| `tests/bots/flows/core/storage/test_agentsflow_lifecycle.py` | CREATE | Same coverage for `AgentsFlow`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Inside the host modules add these:
from typing import Optional, Union
from parrot.bots.flows.core.storage.backends import ResultStorage  # CREATED by TASK-1013
import asyncio  # already imported in all three files
```

### Existing Signatures to Use
```python
# parrot/bots/orchestration/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):                # line 147
    def __init__(                                                 # line 186
        self,
        name: str = "AgentCrew",
        agents: List[Union[BasicAgent, AbstractBot]] = None,
        shared_tool_manager: ToolManager = None,
        max_parallel_tasks: int = 10,
        llm: Optional[Union[str, AbstractClient]] = None,
        auto_configure: bool = True,
        truncation_length: Optional[int] = None,
        truncate_context_summary: bool = True,
        embedding_model: Any = None,
        enable_analysis: bool = False,
        dimension: int = 384,
        index_type: str = "Flat",
        agent_execution_timeout: float = 600.0,
        # NEW (this task):
        # persist_results: bool = True,
        # result_storage: Union[str, "ResultStorage", None] = None,
        **kwargs,
    ): ...

# parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):                # line 86
    def __init__(...)                                             # line 125
# Same shape; same NEW params.

# parrot/bots/flow/fsm.py
class AgentsFlow(PersistenceMixin, SynthesisMixin):               # line 277
    def __init__(                                                 # line 316
        self,
        name: str = "AgentsFlow",
        ...,
        llm: Optional[Union[str, AbstractClient]] = None,
        # NEW (this task):
        # persist_results: bool = True,
        # result_storage: Union[str, "ResultStorage", None] = None,
        **kwargs,
    ): ...
```

### `_save_result` call sites (verified — must each be updated)

```python
# parrot/bots/orchestration/crew.py — 6 sites
# line 1355  run_sequential
# line 1810  run_loop
# line 2121  run_parallel
# line 2354  run_flow inner
# line 2610  run_flow inner
# line 3118  run_flow outer

# parrot/bots/flows/crew/crew.py — 6 sites
# line 1292, 1753, 2071, 2303, 2559, 3067

# parrot/bots/flow/fsm.py — 1 site
# line 944  run_flow (collection='flow_executions')
```

Verify the line numbers BEFORE editing — `grep -n "_save_result\b" parrot/bots/orchestration/crew.py parrot/bots/flows/crew/crew.py parrot/bots/flow/fsm.py`. The codebase may have shifted; the grep is the source of truth.

### Does NOT Exist
- ~~`AgentCrew.aclose`~~ / ~~`AgentCrew.__aenter__`~~ / ~~`AgentCrew.__aexit__`~~ — these come for free from `PersistenceMixin` (TASK-1017). Do not redefine them on the host class.
- ~~`AgentsFlow.aclose`~~ — same; inherited.
- ~~A unified `AgentCrew` class~~ — there are two duplicates by design (out-of-scope to merge).

---

## Implementation Notes

### Constructor wiring (apply identically to all three host classes)

```python
# Inside __init__, AFTER the existing self.* assignments:
import asyncio
from typing import Optional, Union
from parrot.bots.flows.core.storage.backends import ResultStorage

# ...
self._persist_results: bool = persist_results
self._result_storage_arg: Union[str, ResultStorage, None] = result_storage
self._result_storage: Optional[ResultStorage] = (
    result_storage if isinstance(result_storage, ResultStorage) else None
)
self._persist_tasks: set[asyncio.Task] = set()
```

### Call-site update pattern

Apply this transformation everywhere `_save_result` is scheduled:

```diff
- asyncio.get_running_loop().create_task(
+ _persist_task = asyncio.get_running_loop().create_task(
      self._save_result(
          result,
          "run_sequential",
          user_id=user_id,
          session_id=session_id,
      )
  )
+ self._persist_tasks.add(_persist_task)
+ _persist_task.add_done_callback(self._persist_tasks.discard)
```

Use the same pattern even for the AgentsFlow site at fsm.py:944 (the
local `_aio` alias there is just an alternative name for `asyncio` —
the rewrite simplifies it).

### Key Constraints
- The two duplicated `AgentCrew` files must remain byte-equivalent in
  the new params (identical default values, identical docstring lines).
  Diff them after editing as a sanity check:
  `diff <(grep -A2 "persist_results" parrot/bots/orchestration/crew.py) <(grep -A2 "persist_results" parrot/bots/flows/crew/crew.py)`.
- The constructor MUST NOT call `get_result_storage` itself — resolution
  is lazy in the mixin (TASK-1017). This keeps init free of I/O.
- Do NOT override `aclose` / `__aenter__` / `__aexit__` on the host —
  inherit them from the mixin.
- Preserve the fire-and-forget contract. Do not `await` the persist
  task; the existing test suites depend on the immediate return.

### References in Codebase
- `parrot/bots/flow/fsm.py:941-951` — current call site (with `_aio` alias) for reference.
- `parrot/bots/orchestration/crew.py:1355-1364` — current call-site shape.

---

## Acceptance Criteria

- [ ] Both `AgentCrew(...)` constructors accept `persist_results` and `result_storage` kwargs and set the four mixin-owned attributes.
- [ ] `AgentsFlow(...)` accepts the same two kwargs and sets the same four attributes.
- [ ] `AgentCrew(name="x", persist_results=False).run_sequential(...)` opens NO storage connection (no `DocumentDb`, asyncdb pg, or asyncdb redis constructor invoked) and emits NO persistence-related log line.
- [ ] `AgentCrew(name="x", result_storage="postgres").run_flow(...)` causes the Postgres backend to be lazily instantiated and `save()` to be called once.
- [ ] `AgentsFlow(..., result_storage="redis").run_flow(...)` writes one Redis key.
- [ ] Setting only the env var `CREW_RESULT_STORAGE=postgres` (no constructor args) routes results to Postgres.
- [ ] `async with AgentCrew(name="x", result_storage="postgres") as crew:` runs and releases the asyncdb connection on exit (verifiable via mock — exactly one `close()` call).
- [ ] `crew._persist_tasks` shrinks back to empty after `aclose()` returns; the in-flight tasks finished or were awaited.
- [ ] `pytest tests/bots/flows/core/storage/test_agentcrew_lifecycle.py tests/bots/flows/core/storage/test_agentsflow_lifecycle.py -v` is green.
- [ ] `ruff check parrot/bots/orchestration/crew.py parrot/bots/flows/crew/crew.py parrot/bots/flow/fsm.py` is clean.
- [ ] No existing public method signature changes beyond the two additive kwargs.

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_agentcrew_lifecycle.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.bots.flows.core.storage.backends import ResultStorage


class _RecordingStorage(ResultStorage):
    def __init__(self):
        self.saves = []
        self.closed = 0
    async def save(self, collection, document):
        self.saves.append((collection, document))
    async def close(self):
        self.closed += 1


@pytest.mark.asyncio
async def test_persist_results_false_opens_no_connection(monkeypatch):
    """No backend factory call when persist_results=False."""
    from parrot.bots.orchestration.crew import AgentCrew
    factory = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.persistence.get_result_storage",
        factory,
    )
    crew = AgentCrew(name="X", persist_results=False)
    await crew._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_storage_instance_is_used():
    from parrot.bots.orchestration.crew import AgentCrew
    storage = _RecordingStorage()
    crew = AgentCrew(name="X", result_storage=storage)
    await crew._save_result(MagicMock(to_dict=lambda: {"a": 1}), "run_flow")
    assert len(storage.saves) == 1


@pytest.mark.asyncio
async def test_aclose_releases_storage():
    from parrot.bots.orchestration.crew import AgentCrew
    storage = _RecordingStorage()
    async with AgentCrew(name="X", result_storage=storage) as crew:
        await crew._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    assert storage.closed == 1


# tests/bots/flows/core/storage/test_agentsflow_lifecycle.py
# Mirror the AgentCrew tests against AgentsFlow.
```

---

## Agent Instructions

1. **Read the spec** §2 "Lifecycle & Cleanup" and §3 Module 6.
2. **Verify** TASK-1017 is in `tasks/completed/`.
3. **Activate the venv**: `source .venv/bin/activate`.
4. **Re-grep the call sites** before editing — the line numbers in the
   spec/contract are a snapshot:
   ```
   grep -n "_save_result\b" parrot/bots/orchestration/crew.py parrot/bots/flows/crew/crew.py parrot/bots/flow/fsm.py
   ```
5. **Implement** in this order: (a) `parrot/bots/orchestration/crew.py`
   constructor, then its 6 call sites; (b) `parrot/bots/flows/crew/crew.py`
   same; (c) `parrot/bots/flow/fsm.py` constructor + 1 call site.
6. **Diff the two AgentCrew copies** for the new code paths to ensure
   they remain in sync.
7. **Run** the tests scoped to this task plus a quick smoke run of the
   pre-existing crew/flow tests:
   ```
   pytest tests/bots/flows/core/storage/ -v
   pytest tests/bots/orchestration/ -k "crew" -v   # if any exist
   ```
8. **Move this file** to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-05
**Notes**: 13 tests pass (8 AgentCrew + 5 AgentsFlow). All three host classes
wired: orchestration/crew.py (6 call sites), flows/crew/crew.py (6 call
sites), flow/fsm.py (1 call site). Four mixin attrs initialised in each
constructor. fsm.py and flows/crew/crew.py are lint-clean; orchestration/crew.py
has 6 pre-existing F401/F841/F541 issues unrelated to TASK-1018 (out of scope).

**Deviations from spec**: none
