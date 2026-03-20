# TASK-166: Memo Persistence Integration Tests

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (2h)
**Depends-on**: TASK-164, TASK-165
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Integration tests validating end-to-end memo persistence.
> Uses mock pipeline components to test persistence hooks.

---

## Scope

- Create `tests/integration/test_memo_persistence.py`
- Test memo stored after deliberation
- Test events logged after execution
- Test fire-and-forget behavior (pipeline not blocked)
- Mock CommitteeDeliberation and order execution

**NOT in scope**: Live API tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/test_memo_persistence.py` | CREATE | Integration test suite |

---

## Implementation Notes

### Test Structure

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

@pytest.fixture
def memo_store(tmp_path):
    return FileMemoStore(base_path=str(tmp_path / "memos"))

@pytest.fixture
def orchestrator(memo_store):
    return ExecutionOrchestrator(memo_store=memo_store, ...)

class TestMemoPersistenceIntegration:
    async def test_memo_persisted_after_deliberation(
        self,
        orchestrator,
        memo_store,
    ):
        """Verify memo saved after pipeline runs."""
        with patch.object(orchestrator, '_run_deliberation') as mock:
            mock.return_value = sample_memo
            await orchestrator.run_pipeline(...)

        # Allow fire-and-forget task to complete
        await asyncio.sleep(0.1)

        # Verify memo stored
        saved = await memo_store.get(sample_memo.id)
        assert saved is not None
        assert saved.id == sample_memo.id

    async def test_execution_event_logged(
        self,
        orchestrator,
        memo_store,
    ):
        """Verify execution event logged after orders complete."""
        ...

        events = await memo_store.get_events(memo_id=sample_memo.id)
        assert len(events) >= 2  # CREATED + EXECUTION_COMPLETED
        assert events[0].event_type == MemoEventType.EXECUTION_COMPLETED

    async def test_pipeline_not_blocked_by_persistence(
        self,
        orchestrator,
    ):
        """Verify pipeline completes before persistence."""
        start = time.time()
        await orchestrator.run_pipeline(...)
        elapsed = time.time() - start

        # Pipeline should complete quickly
        # Persistence happens in background
        assert elapsed < 1.0
```

---

## Acceptance Criteria

- [x] Test memo stored after deliberation
- [x] Test CREATED event logged
- [x] Test EXECUTION_COMPLETED/FAILED event logged
- [x] Test pipeline timing (not blocked by persistence)
- [x] All tests pass
- [x] Tests use tmp_path for isolation

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Created comprehensive integration test suite for memo persistence hooks:

**File Created**: `tests/integration/test_memo_persistence.py` (13 tests)

### Test Classes

1. **TestMemoPersistenceIntegration** (3 tests)
   - `test_memo_persisted_after_store` - Verifies memo CRUD with FileMemoStore
   - `test_persist_memo_via_orchestrator` - Tests ExecutionOrchestrator._persist_memo()
   - `test_created_event_logged_on_store` - Verifies CREATED event is logged

2. **TestExecutionEventLogging** (3 tests)
   - `test_execution_completed_event_logged` - EXECUTION_COMPLETED on success
   - `test_execution_failed_event_logged` - EXECUTION_FAILED when all orders fail
   - `test_mixed_execution_results` - EXECUTION_COMPLETED if any succeed

3. **TestPipelineTimingBehavior** (4 tests)
   - `test_store_returns_immediately` - store() < 50ms (fire-and-forget)
   - `test_log_event_returns_immediately` - log_event() < 50ms
   - `test_persist_memo_fire_and_forget` - _persist_memo() < 100ms
   - `test_finalize_execution_completes_quickly` - _finalize_execution() < 100ms

4. **TestMemoStoreIsolation** (2 tests)
   - `test_each_test_has_isolated_store` - tmp_path isolation
   - `test_store_isolation_across_tests` - separate stores don't share data

5. **TestEventPersistenceAcrossRestart** (1 test)
   - `test_events_readable_from_new_store_instance` - JSONL survives "restart"

### Verification

```bash
pytest tests/integration/test_memo_persistence.py -v
# 13 passed in 4.36s
```
