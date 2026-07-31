---
type: Wiki Overview
title: 'TASK-1772: SavedExecutionService'
id: doc:sdd-tasks-completed-task-1772-saved-execution-service-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `SavedExecutionService` is the thin orchestration layer between the HTTP
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.base
  rel: mentions
- concept: mod:parrot.handlers.crew.models
  rel: mentions
---

# TASK-1772: SavedExecutionService

**Feature**: FEAT-306 — AgentCrew Saved Crews (Execution Persistence & Replay)
**Spec**: `sdd/specs/agentcrew-saved-crews.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1765, TASK-1768, TASK-1767
**Assigned-to**: unassigned

---

## Context

The `SavedExecutionService` is the thin orchestration layer between the HTTP
handler and the storage/scheduler backends. It coordinates: reading from
`ResultStorage`, replaying by resolving crews via `BotManager`, and scheduling
via `AgentSchedulerManager.add_schedule()`.

Implements spec Module 8.

---

## Scope

- Create `SavedExecutionService` class with methods:
  - `list_executions(tenant, user_id, filters, limit, offset)` — delegates to `storage.list()`
  - `get_execution(tenant, user_id, execution_id)` — delegates to `storage.get()`
  - `replay_execution(tenant, user_id, execution_id)` — fetches record, resolves
    crew via `BotManager.get_crew()`, calls the appropriate `run_*` method with
    the saved prompt. Returns new job info.
  - `schedule_execution(tenant, user_id, execution_id, schedule_config)` — fetches
    record, calls `AgentSchedulerManager.add_schedule(is_crew=True)`. Returns
    schedule info.
  - `delete_execution(tenant, user_id, execution_id)` — delegates to `storage.delete()`
- Handle error cases:
  - Crew not found → raise ValueError or return error dict
  - Prompt missing → raise ValueError
  - Execution not found → return None / raise
- Write unit tests with mocked storage, bot_manager, scheduler_manager

**NOT in scope**: HTTP handler (TASK-1773), storage backend implementations (previous tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/saved_execution_service.py` | CREATE | Service class |
| `tests/unit/test_saved_execution_service.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.storage.backends.base import ResultStorage  # base.py:8
from parrot.handlers.crew.models import ExecutionFilter, ScheduleRequest  # models.py (TASK-1767)

# Server-side imports (ai-parrot-server):
# BotManager — location TBD, accessed via app['bot_manager'] in handlers
# AgentSchedulerManager — packages/ai-parrot-server/src/parrot/scheduler/manager.py:284
```

### Existing Signatures to Use
```python
# ResultStorage (after TASK-1765):
async def list(self, collection, filters=None, limit=20, offset=0) -> list[dict]: ...
async def get(self, collection, record_id) -> Optional[dict]: ...
async def delete(self, collection, record_id) -> bool: ...
async def count(self, collection, filters=None) -> int: ...

# AgentSchedulerManager:
async def add_schedule(
    self, agent_name, schedule_type, schedule_config,
    prompt=None, method_name=None, created_by=None, created_email=None,
    metadata=None, agent_id=None, *, is_crew=False,
    send_result=None, success_callback=None,
    scheduler_type='default', callbacks=None
) -> AgentSchedule: ...  # manager.py:932

# BotManager crew access (VERIFIED at packages/ai-parrot-server/src/parrot/manager/manager.py:2191 —
# corrected from the original contract, which omitted `await` and said
# "or None"; get_crew() is async and ALWAYS returns a 2-tuple, using
# (None, None) for "not found", never a bare None):
# async def get_crew(self, identifier: str, as_new: bool = False, tenant: Optional[str] = None)
#     -> Optional[Tuple[AgentCrew, CrewDefinition]]
# crew, crew_def = await bot_manager.get_crew(crew_id, as_new=True, tenant=tenant)
# if not crew or not crew_def: ...  # "not found" case

# CrewExecutionHandler replay pattern (from execution_handler.py:571):
# crew, crew_def = await self.bot_manager.get_crew(...)
# method = getattr(crew, method_name)
# result = await method(prompt, ...)
```

### Does NOT Exist
- ~~`SavedExecutionService`~~ — does not exist yet; this task creates it
- ~~`ResultStorage.replay()`~~ — no replay method on storage; service coordinates this
- ~~`ResultStorage.schedule()`~~ — no schedule method on storage
- ~~`bot_manager.get_crew(...)` returning bare `None`~~ — CORRECTED: always
  returns a 2-tuple; "not found" is `(None, None)`, not `None`.

---

## Implementation Notes

### Pattern to Follow
```python
from navconfig.logging import logging
from parrot.bots.flows.core.storage.backends.base import ResultStorage


class SavedExecutionService:
    def __init__(self, storage: ResultStorage, bot_manager=None, scheduler_manager=None):
        self.storage = storage
        self.bot_manager = bot_manager
        self.scheduler_manager = scheduler_manager
        self.logger = logging.getLogger("parrot.SavedExecutionService")
        self._collection = "crew_executions"

    async def list_executions(self, tenant, user_id, filters=None, limit=20, offset=0):
        storage_filters = {"tenant": tenant, "user_id": user_id}
        if filters:
            storage_filters.update({k: v for k, v in filters.dict(exclude_none=True).items()})
        items = await self.storage.list(self._collection, storage_filters, limit, offset)
        total = await self.storage.count(self._collection, storage_filters)
        return items, total

    async def replay_execution(self, tenant, user_id, execution_id):
        record = await self.storage.get(self._collection, execution_id)
        if not record:
            raise ValueError(f"Execution {execution_id} not found")
        prompt = record.get("prompt")
        if not prompt:
            raise ValueError("Cannot replay: original prompt not available")
        crew_name = record["crew_name"]
        method_name = record.get("method", "run_sequential")

        crew_entry = self.bot_manager.get_crew(crew_name, tenant=tenant)
        if not crew_entry:
            raise ValueError(f"Crew '{crew_name}' no longer exists")
        crew, crew_def = crew_entry
        # Execute using the saved method
        method = getattr(crew, method_name)
        result = await method(prompt, user_id=user_id)
        return {"crew_name": crew_name, "method": method_name, "status": "submitted"}
```

### Key Constraints
- The service does NOT import or depend on aiohttp — it's framework-agnostic
- Error handling uses exceptions; the handler (TASK-1773) converts to HTTP responses
- `storage.get()` must enforce tenant + user_id scoping (done at storage layer)
- For replay, the correct `run_*` method is determined from `record["method"]`
- `run_parallel` expects `tasks` not `prompt` — need method-specific parameter mapping

### Method-to-Parameter Mapping for Replay

CORRECTED against the verified `AgentCrew` signatures (TASK-1771 fixed the
same two stale entries in that task's contract): `run_loop`'s parameter is
`initial_task`, not `query`; `run`'s parameter is `task`, not `prompt`.

```python
METHOD_PARAM_MAP = {
    "run_sequential": "query",
    "run_loop": "initial_task",   # corrected; also see _UNSUPPORTED_REPLAY_METHODS below
    "run_flow": "initial_task",
    "run_parallel": "tasks",  # needs special handling
    "run": "task",   # corrected
    "ask": "question",
}
```

For `run_parallel`, the saved `prompt` is a single string (the first task's
query at save time — TASK-1771), not the original multi-agent task list;
best-effort replay broadcasts the saved prompt to every agent currently on
the crew. `run_loop` additionally requires a `condition: str` positional
argument that is never persisted with the execution — replay of `run_loop`
executions is therefore unsupported and raises `ValueError`.

---

## Acceptance Criteria

- [ ] `SavedExecutionService` created with storage, bot_manager, scheduler_manager
- [ ] `list_executions()` delegates to storage with tenant+user scoping
- [ ] `get_execution()` delegates to storage with scoping
- [ ] `replay_execution()` resolves crew and calls correct run_* method
- [ ] `replay_execution()` raises ValueError if crew not found
- [ ] `replay_execution()` raises ValueError if prompt missing
- [ ] `schedule_execution()` calls `AgentSchedulerManager.add_schedule(is_crew=True)`
- [ ] `schedule_execution()` accepts all schedule types
- [ ] `delete_execution()` delegates to storage
- [ ] All unit tests pass with mocked dependencies
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_saved_execution_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.list.return_value = [{"id": "abc", "crew_name": "test", "prompt": "query"}]
    storage.get.return_value = {"id": "abc", "crew_name": "test", "prompt": "query", "method": "run_sequential"}
    storage.count.return_value = 1
    storage.delete.return_value = True
    return storage


class TestSavedExecutionService:
    async def test_list_executions(self, mock_storage):
        """list_executions delegates to storage with correct filters."""

    async def test_get_execution(self, mock_storage):
        """get_execution delegates to storage."""

    async def test_replay_success(self, mock_storage):
        """replay resolves crew and calls run_sequential."""

    async def test_replay_crew_not_found(self, mock_storage):
        """replay raises ValueError when crew not found."""

    async def test_replay_no_prompt(self, mock_storage):
        """replay raises ValueError when prompt is None."""

    async def test_schedule_execution(self, mock_storage):
        """schedule calls AgentSchedulerManager.add_schedule with is_crew=True."""

    async def test_delete_execution(self, mock_storage):
        """delete delegates to storage.delete."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1765, TASK-1768, TASK-1767 must be completed
3. **Verify the Codebase Contract** — check BotManager.get_crew() pattern in handler.py
4. **Update status** in `sdd/tasks/index/agentcrew-saved-crews.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1772-saved-execution-service.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Created `SavedExecutionService` with all five methods (`list_executions`,
`get_execution`, `replay_execution`, `schedule_execution`, `delete_execution`).
Corrected two stale contract entries before implementing (per anti-hallucination
protocol, same class of issue found in TASK-1771): `bot_manager.get_crew()` is
`async` and always returns a 2-tuple (`(None, None)` for "not found", never a bare
`None`) — verified at `manager.py:2191`; and the `METHOD_PARAM_MAP` had the same
two stale param names TASK-1771 already fixed (`run_loop` → `initial_task`, not
`query`; `run` → `task`, not `prompt`). Both corrections recorded in the task
file's contract/notes sections. Used `.model_dump(exclude_none=True)` (Pydantic v2)
instead of the task's `.dict()` snippet, and `AgentSchedule.to_dict()` (python-
datamodel `Model`, verified at `scheduler/manager.py:1317`) for the schedule
serialisation. `get_execution()`/`delete_execution()` verify tenant/user_id
ownership in the service layer via `_belongs_to()` — consistent with the deviation
already documented in TASK-1768 (storage-layer `get()`/`delete()` only take
`record_id`, no tenant/user_id params). Created
`tests/unit/test_saved_execution_service.py` covering all 7 scenarios from the
task's Test Specification plus 6 additional edge-case tests (wrong-tenant
ownership check, execution-not-found, run_loop-unsupported, run_parallel
broadcast, no-scheduler-manager, delete-not-found). 13/13 pass. `ruff check` clean.

**Deviations from spec**:
1. `replay_execution()` for `run_parallel` cannot reconstruct the original
   multi-agent task list from the persisted `prompt` (a single string — the first
   task's query at save time, per TASK-1771's `prompt=original_query`). Best-effort:
   broadcasts the saved prompt to every agent currently on the crew
   (`tasks=[{"agent_id": aid, "query": prompt} for aid in crew.agents]`).
2. `replay_execution()` for `run_loop` raises `ValueError` — `run_loop` requires a
   `condition: str` positional argument that is never persisted with the execution
   document, so it cannot be replayed with the current storage schema. Flagging for
   spec review: either accept this limitation permanently, or extend the saved
   document schema with a `condition` field in a follow-up feature.
3. Added a generated `job_id` (`uuid.uuid4()`) to `replay_execution()`'s return
   dict, on top of the task's own `{"crew_name", "method", "status"}` example —
   needed to satisfy the spec's public-interface docstring ("Returns a new job
   dict with job_id"), which the task's own code snippet didn't include.
