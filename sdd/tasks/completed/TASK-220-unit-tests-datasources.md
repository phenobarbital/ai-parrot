# TASK-220: Unit Tests — All Source Types + DatasetManager

**Feature**: DatasetManager Lazy Data Sources (FEAT-030)
**Spec**: `sdd/specs/datasetmanager-datasources.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-213, TASK-214, TASK-215, TASK-216, TASK-217, TASK-218, TASK-219
**Assigned-to**: null

---

## Context

> Full unit test coverage for all new source types and the revised DatasetManager. All tests
> use mocks — no live database or Redis connections. Covers 40 test cases defined in the spec.

---

## Scope

Create `tests/tools/test_datasources.py` with the following test classes:

### `TestInMemorySource`
- `test_inmemory_source_schema` — `prefetch_schema()` returns `{col: dtype_str}` from DataFrame dtypes
- `test_inmemory_source_fetch` — `fetch()` returns the wrapped DataFrame unchanged
- `test_inmemory_cache_key` — `cache_key` == `mem:{name}`

### `TestQuerySlugSource`
- `test_queryslug_fetch_no_params` — `fetch()` calls QS with no conditions
- `test_queryslug_fetch_with_params` — `fetch()` passes params as `conditions=`
- `test_queryslug_schema_prefetch` — single-row QS call infers schema columns
- `test_queryslug_schema_prefetch_failure_ignored` — QS failure returns `{}`, no raise
- `test_queryslug_cache_key` — `cache_key` == `qs:{slug}`

### `TestSQLQuerySource`
- `test_sql_source_param_interpolation` — `{start_date}` interpolated correctly
- `test_sql_source_missing_param_raises` — missing param raises `ValueError`
- `test_sql_source_sql_injection_escaped` — injected string value is escaped (quotes doubled)
- `test_sql_source_cache_key` — `cache_key` == `sql:{driver}:{md5[:8]}`
- `test_sql_source_no_schema` — `prefetch_schema()` returns `{}`

### `TestTableSource`
- `test_table_source_prefetch_pg` — INFORMATION_SCHEMA query run for pg driver
- `test_table_source_prefetch_bigquery` — INFORMATION_SCHEMA query run for bigquery
- `test_table_source_prefetch_mysql` — INFORMATION_SCHEMA query run for mysql
- `test_table_source_prefetch_fallback` — fallback `LIMIT 0` for unknown driver
- `test_table_source_strict_schema_fails` — `prefetch_schema()` error propagates when `strict_schema=True`
- `test_table_source_soft_schema_continues` — `prefetch_schema()` error → empty schema when `strict_schema=False`
- `test_table_source_sql_validation_pass` — SQL containing table name passes
- `test_table_source_sql_validation_fail` — SQL not referencing table raises `ValueError`
- `test_table_source_cache_key` — `cache_key` == `table:{driver}:{table}`

### `TestDatasetEntry`
- `test_dataset_entry_materialize` — `materialize()` calls `source.fetch()` and stores result in `_df`
- `test_dataset_entry_materialize_cached` — second `materialize()` skips fetch if already loaded
- `test_dataset_entry_evict` — `evict()` clears `_df` and `_column_types`, preserves source
- `test_dataset_entry_force_refresh` — `materialize(force=True)` re-fetches even if loaded
- `test_dataset_info_unloaded_table` — `to_info()` exposes schema columns when `loaded=False`

### `TestDatasetManager`
- `test_manager_add_table_source_async` — `add_table_source()` calls `prefetch_schema()` and registers
- `test_manager_add_sql_source_sync` — `add_sql_source()` registers without prefetch
- `test_manager_add_query_backward_compat` — `add_query()` wraps slug in `QuerySlugSource`
- `test_manager_add_dataframe_backward_compat` — `add_dataframe()` wraps df in `InMemorySource`
- `test_manager_materialize_redis_hit` — Redis hit skips `source.fetch()`, restores Parquet df
- `test_manager_materialize_redis_miss` — Redis miss calls `source.fetch()`, serializes to Parquet
- `test_manager_materialize_force_refresh` — `force_refresh=True` bypasses Redis
- `test_manager_evict_single` — `evict("name")` releases df, source retained
- `test_manager_evict_all` — `evict_all()` releases all materialized dfs
- `test_manager_evict_unactive` — `evict_unactive()` only evicts inactive entries
- `test_llm_tool_list_available` — `list_available()` shows unloaded TableSource with schema
- `test_llm_tool_get_metadata` — `get_metadata()` returns DatasetInfo with schema for unloaded entry
- `test_llm_tool_fetch_dataset_table` — `fetch_dataset()` requires `sql=` for TableSource
- `test_llm_tool_fetch_dataset_query_slug` — `fetch_dataset()` works without sql for QuerySlugSource
- `test_llm_tool_evict_dataset` — `evict_dataset()` frees memory
- `test_llm_tool_get_source_schema` — `get_source_schema()` returns schema before load for TableSource
- `test_llm_guide_mixed_states` — guide renders TABLE / QUERY SLUG / SQL / DATAFRAME states
- `test_cache_key_shared_across_agents` — two managers with same slug share same Redis key

### Fixtures to include

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
import io


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'date': pd.to_datetime(['2024-01-01', '2024-01-02']),
        'visits': [100, 150],
        'revenue': [1000.0, 1500.0],
    })


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    return redis


@pytest.fixture
def mock_asyncdb_pg():
    """Mock pg AsyncDB driver returning INFORMATION_SCHEMA rows."""
    driver = AsyncMock()
    driver.fetch = AsyncMock(return_value=[
        {'column_name': 'visit_date', 'data_type': 'date'},
        {'column_name': 'visits', 'data_type': 'integer'},
        {'column_name': 'revenue', 'data_type': 'numeric'},
    ])
    return driver


@pytest.fixture
def redis_with_parquet(sample_df):
    """Mock Redis that returns a Parquet-serialized sample_df."""
    buf = io.BytesIO()
    sample_df.to_parquet(buf, index=False, compression='snappy')
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=buf.getvalue())
    redis.setex = AsyncMock()
    return redis
```

**NOT in scope**: Integration tests (TASK-221). Live DB or Redis connections.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/test_datasources.py` | CREATE | All unit tests per scope above |

---

## Implementation Notes

- Use `@pytest.mark.asyncio` for all async tests.
- Mock `QS` and `MultiQS` at the module level to avoid actual QuerySource calls.
- Mock AsyncDB drivers at the source level, not at the manager level.
- Parquet round-trip test should verify dtypes are preserved post-deserialization.

---

## Acceptance Criteria

- [ ] `tests/tools/test_datasources.py` created with all 40 test cases from the spec
- [ ] All tests use mocks — no live DB or Redis connections
- [ ] All tests pass: `pytest tests/tools/test_datasources.py -v`
- [ ] No existing tests broken: `pytest tests/tools/test_dataset_manager.py -v` still passes

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-datasources.spec.md` (Section 4 — Test Specification)
2. **Check dependencies** — verify TASK-213 through TASK-219 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** all 40 test cases
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-220-unit-tests-datasources.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-03-07
**Notes**:
- Found an existing `tests/tools/test_datasources.py` (58 tests for InMemorySource, QuerySlugSource, MultiQuerySlugSource, SQLQuerySource — created by user for TASK-214/215/216).
- Appended new test classes: `TestTableSource` (10 tests), `TestDatasetEntry` (5 tests), `TestDatasetManagerNewAPI` (20 tests).
- Total: 93 tests pass in `test_datasources.py`, 156 total across both suites.
- AsyncDB is imported inside `TableSource._run_query()` so patched via `asyncdb.AsyncDB` (not module-level).
- MagicMock with `spec=TableSource` doesn't pass `isinstance()` in `to_info()`; used real `TableSource` instance for that test.
- `describe()` attribute on `MagicMock(spec=TableSource)` must be set with `MagicMock(return_value=...)` due to spec enforcement.

**Deviations from spec**:
- Added tests to existing file instead of creating fresh (existing file had 58 tests already covering some scope).
- Test count: 93 (exceeds the 40 specified due to pre-existing tests being retained).
