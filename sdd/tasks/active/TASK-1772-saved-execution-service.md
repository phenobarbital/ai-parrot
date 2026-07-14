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

# BotManager crew access (from handler patterns):
# bot_manager.get_crew(identifier, tenant=tenant) -> tuple[AgentCrew, CrewDefinition] or None
# bot_manager.get_crew(crew_id, as_new=True, tenant=tenant) -> tuple for execution

# CrewExecutionHandler replay pattern (from execution_handler.py):
# crew, crew_def = bot_manager.get_crew(crew_id, as_new=True, tenant=tenant)
# method = getattr(crew, method_name)
# result = await method(prompt, ...)
```

### Does NOT Exist
- ~~`SavedExecutionService`~~ — does not exist yet; this task creates it
- ~~`ResultStorage.replay()`~~ — no replay method on storage; service coordinates this
- ~~`ResultStorage.schedule()`~~ — no schedule method on storage

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
```python
METHOD_PARAM_MAP = {
    "run_sequential": "query",
    "run_loop": "query",
    "run_flow": "initial_task",
    "run_parallel": "tasks",  # needs special handling
    "run": "prompt",
}
```

For `run_parallel`, the saved prompt may be a JSON-serialized task list.

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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
