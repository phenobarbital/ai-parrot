# TASK-422: Implement DeltaTableSource

**Feature**: datasetmanager-sources
**Spec**: `sdd/specs/datasetmanager-sources.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 3 from the spec: the `DeltaTableSource` DataSource subclass.
> Delta Lake is a storage layer that brings ACID transactions to data lakes. The asyncdb
> delta driver wraps `deltalake` + DuckDB for queries.
>
> The owner resolved: use `parrot/interfaces/aws.py` (`AWSInterface`) for S3 credentials.
> Row count estimation must be implemented.

---

## Scope

- Implement `DeltaTableSource(DataSource)` at `sources/deltatable.py`
- Implement `prefetch_schema()`: open connection, call `conn.schema()` to get column→type mapping
- Implement `fetch(**params)`:
  - If `sql` param provided: call `conn.query(sentence=sql, tablename=self._table_name, factory="pandas")` → `(df, error)`
  - If `columns` param provided: call `conn.to_df(columns=columns, factory="pandas")` → `(df, error)`
  - If `filter` param provided: call `conn.query(sentence=filter_expr, factory="pandas")` → `(df, error)`
  - Default (no params): call `conn.to_df(factory="pandas")` for full table
- Implement `describe()`: return human-readable string with path and table name
- Implement `cache_key` property: format `delta:{md5(path)[:12]}`
- Implement `prefetch_row_count()` for LLM size warnings
- Implement static/class method `create_from_parquet(delta_path, parquet_path, table_name, mode)`:
  - Call `driver.create(delta_path, parquet_path, name=table_name, mode=mode)`
- Support local paths, `s3://`, and `gs://` via asyncdb
- For S3 credentials: use `AWSInterface` from `parrot/interfaces/aws.py`
- Write unit tests for all the above

**NOT in scope**: DatasetManager registration method (TASK-423), time-travel queries, schema evolution

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/deltatable.py` | CREATE | DeltaTableSource implementation |
| `packages/ai-parrot/tests/tools/test_deltatable_source.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
import hashlib
from .base import DataSource
from parrot._imports import lazy_import

class DeltaTableSource(DataSource):
    def __init__(
        self,
        path: str,
        name: str,
        table_name: Optional[str] = None,
        mode: str = "error",
        credentials: Optional[Dict] = None,
    ):
        self._path = path
        self._name = name
        self._table_name = table_name or name.upper()
        self._mode = mode
        self._credentials = credentials
        self._schema: Dict[str, str] = {}

    @property
    def cache_key(self) -> str:
        path_hash = hashlib.md5(self._path.encode()).hexdigest()[:12]
        return f"delta:{path_hash}"

    async def prefetch_schema(self) -> Dict[str, str]:
        delta = lazy_import("asyncdb.drivers.delta", ...)
        params = {"path": self._path}
        driver = delta(params=params)
        async with await driver.connection() as conn:
            self._schema = conn.schema()
        return self._schema
```

### Key Constraints
- asyncdb delta driver API:
  - `delta(params={"path": "..."})` or `AsyncDB('delta', params={"path": "..."})`
  - `driver.create(delta_path, parquet_path, name=table_name, mode=mode)`
  - `conn.schema()` → dict of column→type
  - `conn.to_df(columns=[...], factory="pandas")` → `(df, error)`
  - `conn.query(sentence=filter_or_sql, factory="pandas")` → `(df, error)`
  - `conn.query(sentence=sql, tablename=table_name, factory="pandas")` → `(df, error)` for DuckDB SQL
- For S3 paths: use `AWSInterface` from `parrot/interfaces/aws.py` for default credentials
- `mode` values: `overwrite`, `append`, `error`, `ignore`
- `table_name` is used as DuckDB alias for SQL queries

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py` — pattern to follow
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py` — DataSource ABC
- `packages/ai-parrot/src/parrot/interfaces/aws.py` — AWSInterface for S3 credentials
- asyncdb delta driver: `https://github.com/phenobarbital/asyncdb/blob/master/asyncdb/drivers/delta.py`

---

## Acceptance Criteria

- [ ] `DeltaTableSource` inherits from `DataSource` and implements all abstract methods
- [ ] `prefetch_schema()` returns column→type mapping via `conn.schema()`
- [ ] `fetch(sql=...)` queries via `conn.query()` with DuckDB SQL and tablename
- [ ] `fetch(columns=[...])` selects specific columns via `conn.to_df()`
- [ ] `fetch(filter=...)` queries with filter expression
- [ ] `create_from_parquet()` creates Delta table from Parquet file
- [ ] `cache_key` returns `delta:{md5(path)[:12]}`
- [ ] Row count estimation implemented
- [ ] S3 path support uses `AWSInterface` for credentials
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_deltatable_source.py -v`
- [ ] Import works: `from parrot.tools.dataset_manager.sources.deltatable import DeltaTableSource`

---

## Test Specification

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_delta_connection():
    conn = AsyncMock()
    conn.schema.return_value = {
        'pickup_datetime': 'timestamp',
        'passenger_count': 'int64',
        'fare_amount': 'float64',
    }
    conn.to_df = AsyncMock(return_value=(
        pd.DataFrame({'passenger_count': [1, 2], 'fare_amount': [10.5, 20.0]}), None
    ))
    conn.query = AsyncMock(return_value=(
        pd.DataFrame({'passenger_count': [6], 'fare_amount': [35.0]}), None
    ))
    return conn


class TestDeltaTableSource:
    async def test_prefetch_schema(self, mock_delta_connection):
        """prefetch_schema calls conn.schema() and returns column→type dict."""
        ...

    async def test_fetch_with_sql(self, mock_delta_connection):
        """fetch(sql=...) calls conn.query() with tablename."""
        ...

    async def test_fetch_with_columns(self, mock_delta_connection):
        """fetch(columns=[...]) calls conn.to_df(columns=...)."""
        ...

    async def test_fetch_with_filter(self, mock_delta_connection):
        """fetch(filter=...) calls conn.query(sentence=filter)."""
        ...

    def test_cache_key(self):
        """cache_key format: delta:{md5(path)[:12]}."""
        ...

    def test_describe(self):
        """describe() includes path and table name."""
        ...

    async def test_create_from_parquet(self):
        """create_from_parquet creates Delta table from Parquet file."""
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
6. **Move this file** to `tasks/completed/TASK-422-deltatable-source.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
