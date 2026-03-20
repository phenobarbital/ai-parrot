# TASK-221: Integration Tests — DatasetManager Data Sources

**Feature**: DatasetManager Lazy Data Sources (FEAT-030)
**Spec**: `sdd/specs/datasetmanager-datasources.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-219, TASK-220
**Assigned-to**: claude-sonnet-4-6-session-TASK221

---

## Context

> End-to-end integration tests verifying the complete lifecycle: register source → schema
> prefetch → LLM guide → materialize → Redis cache → evict. Validates backward compat with
> existing PandasAgent usage. All tests use mocked AsyncDB drivers and Redis — no live connections.

---

## Scope

Create `tests/tools/test_datasetmanager_integration.py` with the following tests:

### `TestTableSourceFullFlow`

**`test_table_source_full_flow_pg`**
1. Create `DatasetManager` with mock Redis.
2. `await manager.add_table_source("orders", table="public.orders", driver="pg")` with mocked pg driver.
3. Assert: source registered, `entry.loaded == False`.
4. Assert: `list_available()` output contains column names from mock schema.
5. Assert: LLM guide shows `[TABLE — not loaded]` with column list.
6. Call `fetch_dataset("orders", sql="SELECT * FROM public.orders LIMIT 10")` with mocked fetch.
7. Assert: `entry.loaded == True`, shape correct.

**`test_table_source_full_flow_bigquery`**
Same flow against BigQuery mock driver.

**`test_table_source_sql_validation_integration`**
- Register TableSource for `troc.finance_visits_details`.
- Call `fetch_dataset("finance_visits", sql="SELECT * FROM orders LIMIT 10")` (wrong table).
- Assert: raises `ValueError` mentioning the expected table name.

### `TestSQLSourceFlow`

**`test_sql_source_parameterized_query`**
1. `manager.add_sql_source("report", sql="SELECT * FROM orders WHERE date >= '{start}'", driver="pg")`
2. `await manager.materialize("report", start="2024-01-01")` with mocked driver.
3. Assert: df returned, Redis `setex` called with Parquet bytes.
4. Call `materialize("report", start="2024-01-01")` again — assert Redis `get` hit, `source.fetch` NOT called again.

**`test_sql_source_force_refresh`**
1. Materialize to populate Redis.
2. `await manager.materialize("report", force_refresh=True, start="2024-01-01")`.
3. Assert: `source.fetch` called again despite Redis hit.

### `TestQuerySlugFlow`

**`test_query_slug_materialize_and_cache`**
1. `manager.add_query("daily", query_slug="troc_daily_report")`
2. `await manager.materialize("daily")` — assert QS called, Redis written.
3. Second `materialize` — assert Redis hit, QS NOT called again.

### `TestBackwardCompat`

**`test_backward_compat_add_dataframe`**
- `manager.add_dataframe("local", df=sample_df)` → entry uses `InMemorySource`.
- `await manager.materialize("local")` → returns same df.
- Verify no Redis writes (InMemorySource doesn't need caching? — or it does write; check spec behavior).

**`test_backward_compat_add_query`**
- `manager.add_query("slug_data", query_slug="some_slug")` → entry uses `QuerySlugSource`.
- Source registered and `entry.source` is `QuerySlugSource` instance.

### `TestParquetRoundtrip`

**`test_parquet_roundtrip_dtypes`**
- Create df with int64, float64, datetime64, object columns.
- Serialize to Parquet → deserialize.
- Assert all dtypes match original.

**`test_parquet_roundtrip_values`**
- Serialize and deserialize; assert values equal (use `pd.testing.assert_frame_equal`).

### `TestMultipleSourcesMixed`

**`test_multiple_sources_same_manager`**
- Register one of each: InMemorySource, QuerySlugSource, SQLQuerySource, TableSource.
- Call `list_available()` — assert all 4 appear with correct `source_type`.
- Call `get_metadata("table_entry")` — assert schema present despite `loaded=False`.
- Materialize the InMemorySource — assert `loaded=True` for that entry only.

### `TestCacheKeySharing`

**`test_cache_key_shared_across_managers`**
- Create two `DatasetManager` instances with same mock Redis.
- Both register `QuerySlugSource("same_slug")`.
- Materialize in manager1 → Redis written.
- Materialize in manager2 → Redis hit (QS not called in manager2).
- Assert `source.cache_key` is identical in both managers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/test_datasetmanager_integration.py` | CREATE | Integration tests per scope above |

---

## Implementation Notes

- Use `@pytest.mark.asyncio` for all async tests.
- `patch` QS at import level in source modules to avoid real QuerySource calls.
- Use the `redis_with_parquet` fixture from `test_datasources.py` or define equivalents here.
- `pd.testing.assert_frame_equal` for value comparisons.

---

## Acceptance Criteria

- [ ] `tests/tools/test_datasetmanager_integration.py` created with all tests per scope
- [ ] TableSource full flow (pg + BigQuery) passes end-to-end with mocked drivers
- [ ] SQL source parameterized query + Redis cache hit/miss verified
- [ ] Parquet round-trip preserves dtypes and values
- [ ] Backward compat tests confirm `add_dataframe` and `add_query` APIs unchanged
- [ ] Cache key sharing across two managers verified
- [ ] All tests pass: `pytest tests/tools/test_datasetmanager_integration.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-datasources.spec.md` (Section 4 Integration Tests)
2. **Check dependencies** — verify TASK-219, TASK-220 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** all integration tests
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-221-integration-tests-datasources.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6-session-TASK221
**Date**: 2026-03-07
**Notes**: Created `tests/tools/test_datasetmanager_integration.py` with 17 integration tests covering all 7 scenarios from the spec. All 17 tests pass alongside the 93 unit tests in `test_datasources.py` (110 total).

**Deviations from spec**:
- `InMemorySource` reports `source_type="dataframe"` (not `"memory"`) per existing `to_info()` mapping; test asserts `in ("memory", "dataframe")` to be forward-compatible.
- Parquet roundtrip via Redis uses a `QuerySlugSource` entry (not `InMemorySource`) since InMemorySource is already in-memory and bypasses Redis write.
- SQL patch target is `parrot.tools.dataset_manager.sources.sql.AsyncDB` (not `asyncdb.AsyncDB`) since `AsyncDB` is imported at module level in `sql.py`.
