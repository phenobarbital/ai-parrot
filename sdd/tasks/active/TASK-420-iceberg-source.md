# TASK-420: Implement IcebergSource

**Feature**: datasetmanager-sources
**Spec**: `sdd/specs/datasetmanager-sources.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 1 from the spec: the `IcebergSource` DataSource subclass.
> Apache Iceberg is a lakehouse table format that supports schema evolution, partitioning,
> and SQL queries via DuckDB. The asyncdb iceberg driver wraps `pyiceberg` and provides
> a unified async interface for table operations.
>
> The owner resolved that `catalog_params` must always be explicitly provided (no defaults).
> Row count estimation must be implemented (like `TableSource.prefetch_row_count()`).

---

## Scope

- Implement `IcebergSource(DataSource)` at `sources/iceberg.py`
- Implement `prefetch_schema()`: call `driver.load_table(table_id)` then `driver.schema()` to get column→type mapping without fetching rows
- Implement `fetch(**params)`:
  - If `sql` param provided: call `driver.query(sql, table_id=self.table_id, factory="pandas")` — returns `(df, error)` tuple
  - If no `sql`: call `driver.to_df(self.table_id, factory="pandas")` for full table fetch
- Implement `describe()`: return human-readable string with table_id and catalog info
- Implement `cache_key` property: format `iceberg:{table_id}`
- Implement `prefetch_row_count()` method for LLM size warnings
- Implement static/class method `create_table_from_df(driver, df, table_id, namespace, mode)`:
  - Create namespace if needed via `driver.create_namespace(namespace)`
  - Infer PyArrow schema from DataFrame dtypes
  - Call `driver.create_table(table_id, schema=schema)`
  - Call `driver.write(df, table_id, mode=mode)`
- Write unit tests for all the above

**NOT in scope**: DatasetManager registration method (TASK-423), exports (TASK-424)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/iceberg.py` | CREATE | IcebergSource implementation |
| `packages/ai-parrot/tests/tools/test_iceberg_source.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the same pattern as TableSource in sources/table.py:
# - Use lazy_import for asyncdb driver
# - Use logging.getLogger(__name__)
# - Constructor stores config, prefetch_schema does the async work
# - fetch() uses AsyncDB context manager pattern

from parrot._imports import lazy_import
from .base import DataSource

class IcebergSource(DataSource):
    def __init__(self, table_id: str, name: str, catalog_params: Dict[str, Any], ...):
        self._table_id = table_id
        self._name = name
        self._catalog_params = catalog_params
        self._schema: Dict[str, str] = {}

    async def prefetch_schema(self) -> Dict[str, str]:
        # Use asyncdb iceberg driver
        iceberg = lazy_import("asyncdb.drivers.iceberg", ...)
        driver = iceberg(params=self._catalog_params)
        async with await driver.connection() as conn:
            await conn.load_table(self._table_id)
            self._schema = conn.schema()
        return self._schema
```

### Key Constraints
- `catalog_params` is always required (no default resolution) — per owner decision
- Must implement row count estimation for LLM size warnings
- Use `factory="pandas"` for all query calls
- asyncdb iceberg driver API:
  - `driver.query(sql, table_id=..., factory="pandas")` → `(result, error)`
  - `driver.queryrow(sql, table_id=..., factory="pandas")` → `(row, error)`
  - `driver.to_df(table_id, factory="pandas")` → `DataFrame`
  - `driver.load_table(table_id)` → loads table metadata
  - `driver.schema()` → dict of column→type
  - `driver.tables(namespace)` → list of table names
  - `driver.create_namespace(name, properties=...)` → creates namespace
  - `driver.create_table(table_id, schema=pa_schema)` → creates table
  - `driver.write(df, table_id, mode=...)` → writes data

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py` — pattern to follow
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py` — DataSource ABC
- asyncdb iceberg driver: `https://github.com/phenobarbital/asyncdb/blob/master/asyncdb/drivers/iceberg.py`

---

## Acceptance Criteria

- [ ] `IcebergSource` inherits from `DataSource` and implements all abstract methods
- [ ] `prefetch_schema()` returns column→type mapping via `driver.schema()`
- [ ] `fetch(sql=...)` queries via `driver.query()` with DuckDB SQL
- [ ] `fetch()` without sql returns full table via `driver.to_df()`
- [ ] `create_table_from_df()` creates namespace, schema, table, and writes data
- [ ] `cache_key` returns `iceberg:{table_id}`
- [ ] Row count estimation implemented
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_iceberg_source.py -v`
- [ ] Import works: `from parrot.tools.dataset_manager.sources.iceberg import IcebergSource`

---

## Test Specification

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'city': ['Berlin', 'Tokyo', 'Lima'],
        'population': [3432000, 13960000, 9750000],
        'country': ['DE', 'JP', 'PE'],
    })


@pytest.fixture
def mock_iceberg_driver():
    driver = AsyncMock()
    driver.schema.return_value = {
        'city': 'string', 'population': 'int64', 'country': 'string',
    }
    driver.to_df = AsyncMock(return_value=pd.DataFrame({
        'city': ['Berlin'], 'population': [3432000], 'country': ['DE']
    }))
    driver.query = AsyncMock(return_value=(
        pd.DataFrame({'city': ['Tokyo'], 'population': [13960000]}), None
    ))
    return driver


class TestIcebergSource:
    async def test_prefetch_schema(self, mock_iceberg_driver):
        """prefetch_schema calls load_table + schema() and returns column→type dict."""
        ...

    async def test_fetch_with_sql(self, mock_iceberg_driver):
        """fetch(sql=...) calls driver.query() with table_id and factory."""
        ...

    async def test_fetch_full_table(self, mock_iceberg_driver):
        """fetch() without sql calls driver.to_df()."""
        ...

    def test_cache_key(self):
        """cache_key format: iceberg:{table_id}."""
        ...

    def test_describe(self):
        """describe() includes table_id."""
        ...

    async def test_create_table_from_df(self, mock_iceberg_driver, sample_df):
        """create_table_from_df creates namespace, schema, writes df."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-sources.spec.md` for full context
2. **Check dependencies** — no dependencies for this task
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-420-iceberg-source.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
