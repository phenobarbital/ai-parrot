# TASK-162: FileMemoStore Unit Tests

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (2h)
**Depends-on**: TASK-159, TASK-161
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Comprehensive unit tests for FileMemoStore.
> Tests CRUD operations, cache behavior, and event logging.

---

## Scope

- Create `tests/test_memo_store.py`
- Create `tests/fixtures/investment_memo_fixture.json`
- Test store/get/get_by_date/query operations
- Test cache eviction (LRU policy)
- Test event logging and querying
- Test memo serialization round-trip
- Use pytest-asyncio and tmp_path fixture

**NOT in scope**: Integration tests with pipeline.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_memo_store.py` | CREATE | Unit test suite |
| `tests/fixtures/investment_memo_fixture.json` | CREATE | Sample memo data |

---

## Implementation Notes

### Test Structure

```python
import pytest
from pathlib import Path

@pytest.fixture
def memo_store(tmp_path):
    return FileMemoStore(base_path=str(tmp_path / "memos"))

@pytest.fixture
def sample_memo():
    return InvestmentMemo(
        id="test-memo-001",
        created_at=datetime.utcnow(),
        ...
    )

class TestFileMemoStore:
    async def test_store_creates_file(self, memo_store, sample_memo):
        """Verify memo stored at correct path."""

    async def test_get_returns_memo(self, memo_store, sample_memo):
        """Store then retrieve memo."""

    async def test_get_not_found_returns_none(self, memo_store):
        """Get non-existent memo returns None."""

    async def test_get_by_date_filters_correctly(self, memo_store):
        """Memos filtered by date range."""

    async def test_query_by_ticker(self, memo_store):
        """Query filters by ticker."""

    async def test_query_by_consensus(self, memo_store):
        """Query filters by consensus level."""

class TestMemoStoreCache:
    async def test_cache_hit(self, memo_store, sample_memo):
        """Second get comes from cache."""

    async def test_cache_eviction(self, memo_store):
        """Oldest evicted when cache full."""

class TestMemoEventLog:
    async def test_log_event_creates_file(self, memo_store):
        """Event logged to JSONL file."""

    async def test_get_events_filters(self, memo_store):
        """Events filtered by memo_id and type."""

class TestMemoSerialization:
    async def test_roundtrip_all_fields(self, memo_store, sample_memo):
        """All fields preserved after store/get."""
```

---

## Acceptance Criteria

- [x] Tests for store(), get(), get_by_date(), query()
- [x] Tests for cache hit/miss behavior
- [x] Tests for LRU eviction
- [x] Tests for log_event() and get_events()
- [x] Tests for serialization round-trip
- [x] All tests pass
- [x] Coverage > 80% for memo_store module

---

## Completion Note

**Completed**: 2026-03-04
**Implemented by**: claude-session

### Summary

Created comprehensive unit test suite with **29 tests** across 5 test classes:

1. **TestFileMemoStore** (10 tests):
   - `test_store_creates_file` - Verifies date-organized path
   - `test_store_returns_memo_id` - Returns correct ID
   - `test_get_returns_memo` - Store/retrieve cycle
   - `test_get_not_found_returns_none` - Missing memo handling
   - `test_get_by_date_filters_correctly` - Date range queries
   - `test_get_by_date_chronological_order` - Oldest first ordering
   - `test_query_by_ticker` - Ticker filtering
   - `test_query_by_consensus` - Consensus level filtering
   - `test_query_respects_limit` - Limit parameter
   - `test_query_newest_first` - Newest first ordering

2. **TestMemoStoreCache** (3 tests):
   - `test_cache_hit` - Cache retrieval
   - `test_cache_eviction` - LRU eviction when full
   - `test_cache_updated_on_store` - Immediate cache update

3. **TestMemoEventLog** (7 tests):
   - `test_log_event_creates_file` - JSONL file creation
   - `test_log_event_appends` - Multiple events
   - `test_get_events_filters_by_memo_id` - memo_id filter
   - `test_get_events_filters_by_type` - event_type filter
   - `test_get_events_newest_first` - Timestamp ordering
   - `test_get_events_respects_limit` - Limit parameter
   - `test_all_event_types_supported` - All 6 event types

4. **TestMemoSerialization** (5 tests):
   - `test_roundtrip_basic_fields` - Core fields preserved
   - `test_roundtrip_recommendations` - Nested recommendations
   - `test_roundtrip_portfolio_snapshot` - Complex nested object
   - `test_roundtrip_datetime_fields` - Datetime serialization
   - `test_roundtrip_enums` - Enum value preservation

5. **TestEdgeCases** (4 tests):
   - `test_empty_recommendations` - Empty list handling
   - `test_special_characters_in_summary` - Unicode/special chars
   - `test_get_events_empty` - Empty event log
   - `test_get_by_date_empty` - No matching memos

### Files Created

- `tests/test_memo_store.py` (450+ lines)
- `tests/fixtures/investment_memo_fixture.json`

### Test Results

```
29 passed in 8.30s
```

All tests use `tmp_path` fixture for isolation and `pytest-asyncio` for async support.
