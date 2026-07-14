# TASK-1774: Integration Tests

**Feature**: FEAT-307 — AgentCrew Saved Crews (Execution Persistence & Replay)
**Spec**: `sdd/specs/agentcrew-saved-crews.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1773, TASK-1771
**Assigned-to**: unassigned

---

## Context

End-to-end integration tests that verify the full flow: save an execution via
`run_*`, list it via the API, replay it, schedule it, and delete it. These tests
exercise the complete stack from handler to storage backend.

Implements spec Module 10.

---

## Scope

- Write integration tests covering:
  - Save-and-list roundtrip: save via `_save_result()` with prompt/tenant, then
    list via `SavedExecutionService` and verify prompt is present
  - Replay creates new execution: replay a saved record, verify a new execution
    record is created
  - Schedule from execution: schedule a saved execution, verify `AgentSchedule`
    record created
  - Tenant isolation: user A cannot see user B's executions
  - Pagination: verify offset/limit and total count
- Tests should use mocked storage backends (not real Postgres/Redis) unless
  integration infrastructure is available
- Verify error paths: crew not found, prompt missing, execution not found

**NOT in scope**: Performance testing, load testing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/test_saved_executions_flow.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All imports from previous tasks:
from parrot.bots.flows.core.storage.backends.base import ResultStorage
from parrot.bots.flows.core.storage.backends.postgres import PostgresResultStorage
from parrot.bots.flows.core.storage.persistence import PersistenceMixin
# from parrot.handlers.crew.saved_execution_service import SavedExecutionService  # TASK-1772
# from parrot.handlers.crew.models import ExecutionFilter, ScheduleRequest  # TASK-1767
```

### Does NOT Exist
- ~~`tests/integration/test_saved_executions_flow.py`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
Use pytest-asyncio fixtures to set up mocked services:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_storage():
    """In-memory mock implementing ResultStorage read/write."""
    storage = AsyncMock()
    records = []
    # Wire save/list/get/delete to manipulate records list
    return storage


@pytest.fixture
def service(mock_storage):
    """SavedExecutionService with mocked backends."""
    from parrot.handlers.crew.saved_execution_service import SavedExecutionService
    return SavedExecutionService(
        storage=mock_storage,
        bot_manager=MagicMock(),
        scheduler_manager=AsyncMock(),
    )
```

### Key Constraints
- Tests should be runnable without a real database
- Use `pytest.mark.asyncio` for async tests
- Follow existing test patterns in `tests/`
- Test both happy paths and error paths

---

## Acceptance Criteria

- [ ] Save-and-list roundtrip test passes
- [ ] Replay creates new execution test passes
- [ ] Schedule from execution test passes
- [ ] Tenant isolation test passes
- [ ] Pagination test passes
- [ ] Error path tests pass (crew not found, prompt missing, execution not found)
- [ ] All tests pass: `pytest tests/integration/test_saved_executions_flow.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/integration/test_saved_executions_flow.py
import pytest


class TestSavedExecutionsFlow:
    async def test_save_and_list_roundtrip(self, service, mock_storage):
        """Save execution with prompt, list it, verify prompt present."""

    async def test_replay_creates_new_execution(self, service, mock_storage):
        """Replay a saved execution, verify new record created."""

    async def test_schedule_from_execution(self, service, mock_storage):
        """Schedule a saved execution, verify AgentSchedule created."""

    async def test_tenant_isolation(self, service, mock_storage):
        """User A cannot see user B's executions."""

    async def test_pagination(self, service, mock_storage):
        """Verify offset/limit and total count correctness."""

    async def test_replay_crew_not_found(self, service, mock_storage):
        """Replay fails with ValueError when crew deleted."""

    async def test_replay_no_prompt(self, service, mock_storage):
        """Replay fails with ValueError when prompt missing."""

    async def test_get_execution_not_found(self, service, mock_storage):
        """Get returns None for nonexistent execution."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1773 and TASK-1771 must be completed
3. **Verify the Codebase Contract** — confirm all service and model imports
4. **Update status** in `sdd/tasks/index/agentcrew-saved-crews.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1774-integration-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
