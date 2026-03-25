# TASK-425: Integration Tests for New DatasetManager Sources

**Feature**: datasetmanager-sources
**Spec**: `sdd/specs/datasetmanager-sources.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-423, TASK-424
**Assigned-to**: unassigned

---

## Context

> This task implements Module 6 from the spec: comprehensive integration tests that
> verify the full flow from registration through materialization for all three new
> source types, plus a mixed-sources test with all 9 source types.

---

## Scope

- Write integration tests at `packages/ai-parrot/tests/tools/test_dataset_new_sources_integration.py`
- Test full flows:
  - Iceberg: register → schema prefetched → guide shows columns → `fetch_dataset(sql=...)` materializes df
  - Mongo: register → schema from find_one → `fetch_dataset(filter={...}, projection={...})` materializes df
  - Delta: register → schema prefetched → `fetch_dataset(sql=...)` materializes df
  - Create Iceberg from df → register → query back → verify round-trip
  - Create Delta from Parquet → register → query back → verify round-trip
  - Mixed: register all 9 source types → `list_available()` → metadata correct for each
- All integration tests use mocked asyncdb drivers (no real database connections needed)
- Verify Redis caching integration (mock Redis) for new source types
- Verify guide generation includes correct usage hints for each new source type

**NOT in scope**: Real database connections, performance benchmarks

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/test_dataset_new_sources_integration.py` | CREATE | Integration tests |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the pattern in existing tests at tests/tools/
import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.tools.dataset_manager import DatasetManager


@pytest.fixture
def manager():
    return DatasetManager()


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    return redis
```

### Key Constraints
- Use `@pytest.mark.asyncio` for async tests
- Mock asyncdb drivers at the import level
- Verify that `DatasetInfo` objects have correct `source_type` values
- Verify guide content includes appropriate hints (SQL for Iceberg/Delta, filter for Mongo)
- Test error cases: Mongo without filter, Iceberg without catalog_params

### References in Codebase
- `packages/ai-parrot/tests/tools/` — existing test patterns
- Spec section 4 "Test Specification" — integration test table

---

## Acceptance Criteria

- [ ] `test_iceberg_full_flow` — register → prefetch → guide → fetch → materialize
- [ ] `test_mongo_full_flow` — register → prefetch → guide → fetch with filter → materialize
- [ ] `test_deltatable_full_flow` — register → prefetch → guide → fetch → materialize
- [ ] `test_create_iceberg_and_query` — create from df → register → query → verify
- [ ] `test_create_deltatable_and_query` — create from parquet → register → query → verify
- [ ] `test_mixed_sources_all_types` — all 9 types → list_available → correct metadata
- [ ] Redis cache flow tested for new source types
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_dataset_new_sources_integration.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
class TestIcebergFullFlow:
    async def test_register_prefetch_fetch(self):
        """Register Iceberg → schema prefetched → fetch_dataset(sql=...) works."""
        ...


@pytest.mark.asyncio
class TestMongoFullFlow:
    async def test_register_prefetch_fetch(self):
        """Register Mongo → schema from find_one → fetch with filter+projection works."""
        ...

    async def test_fetch_without_filter_fails(self):
        """fetch_dataset without filter raises ValueError."""
        ...


@pytest.mark.asyncio
class TestDeltaFullFlow:
    async def test_register_prefetch_fetch(self):
        """Register Delta → schema prefetched → fetch_dataset(sql=...) works."""
        ...


@pytest.mark.asyncio
class TestCreateAndQuery:
    async def test_create_iceberg_from_df_and_query(self):
        """Create Iceberg from DataFrame → register → query back → verify."""
        ...

    async def test_create_deltatable_from_parquet_and_query(self):
        """Create Delta from Parquet → register → query back → verify."""
        ...


@pytest.mark.asyncio
class TestMixedSources:
    async def test_all_nine_source_types(self):
        """Register all 9 source types → list_available → metadata correct."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-sources.spec.md` for full context
2. **Check dependencies** — verify TASK-423, TASK-424 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-425-new-sources-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-03-25
**Notes**: Created 24 integration tests in 7 test classes covering the full flow for
IcebergSource, MongoSource, and DeltaTableSource. All tests use mocked asyncdb drivers.
Redis caching integration tested with mock Redis. Guide generation verified.

Key implementation decisions:
- `fetch_dataset()` returns a dict (LLM tool interface); tests use `manager.materialize()`
  directly for DataFrame assertions
- Mongo fetch params passed as kwargs: `filter=`, `projection=` (not wrapped in `conditions=`)
- Delta column selection passed as `columns=[...]` kwarg to `materialize()`
- TableSource patched via `patch.object(TableSource, "_run_query", ...)` since TableSource
  uses `asyncdb.AsyncDB` internally (no `_get_driver` method)
- All 127 tests in `packages/ai-parrot/tests/tools/` pass

**Deviations from spec**: none
