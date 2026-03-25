# TASK-429: Core SQL Sources — PostgreSQL, MySQL, SQLite

**Feature**: DatabaseToolkit
**Feature ID**: FEAT-062
**Spec**: `sdd/specs/databasetoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-427, TASK-428
**Assigned-to**: unassigned

---

## Context

These three SQL sources are the most commonly used and serve as the reference
implementation pattern for all other SQL sources. They share the same structure:
set `driver` and `sqlglot_dialect`, inherit `validate_query()` from the base class,
query `information_schema` for metadata, and use asyncdb for execution.

Implements **Modules 3, 4, 5** from the spec.

---

## Scope

- Implement `PostgresSource` — driver `"pg"`, sqlglot dialect `"postgres"`,
  metadata via `information_schema.tables`/`information_schema.columns`.
- Implement `MySQLSource` — driver `"mysql"`, sqlglot dialect `"mysql"`,
  metadata via `information_schema`.
- Implement `SQLiteSource` — driver `"sqlite"`, sqlglot dialect `"sqlite"`,
  metadata via `pragma_table_info` / `sqlite_master`.
- Each source must:
  - Register via `@register_source(driver)`
  - Implement `get_default_credentials()` using `parrot.interfaces.database.get_default_credentials`
  - Implement `get_metadata(credentials, tables)` → `MetadataResult`
  - Implement `query(credentials, sql, params)` → `QueryResult`
  - Implement `query_row(credentials, sql, params)` → `RowResult`

**NOT in scope**: BigQuery, MSSQL, Oracle, ClickHouse, DuckDB (other tasks),
non-SQL sources.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/sources/postgres.py` | CREATE | PostgresSource |
| `parrot/tools/database/sources/mysql.py` | CREATE | MySQLSource |
| `parrot/tools/database/sources/sqlite.py` | CREATE | SQLiteSource |

---

## Implementation Notes

### Pattern to Follow
```python
# sources/postgres.py
from __future__ import annotations
import logging
import time
from typing import Any

from asyncdb import AsyncDB
from parrot.tools.database.base import (
    AbstractDatabaseSource, MetadataResult, QueryResult,
    RowResult, TableMeta, ColumnMeta,
)
from parrot.tools.database.sources import register_source


@register_source("pg")
class PostgresSource(AbstractDatabaseSource):
    driver = "pg"
    sqlglot_dialect = "postgres"

    def __init__(self):
        self.logger = logging.getLogger("Parrot.Toolkits.Database.Postgres")

    async def get_default_credentials(self) -> dict[str, Any]:
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("pg")
        return {"dsn": dsn} if dsn else {}

    async def get_metadata(
        self, credentials: dict[str, Any], tables: list[str] | None = None
    ) -> MetadataResult:
        # Use asyncdb to query information_schema.columns
        # Build TableMeta + ColumnMeta from results
        ...

    async def query(
        self, credentials: dict[str, Any], sql: str,
        params: dict[str, Any] | None = None
    ) -> QueryResult:
        start = time.monotonic()
        # Use asyncdb to execute query, measure time
        ...

    async def query_row(
        self, credentials: dict[str, Any], sql: str,
        params: dict[str, Any] | None = None
    ) -> RowResult:
        # Same as query but LIMIT 1 / fetchone
        ...
```

### Key Constraints
- All DB access goes through `asyncdb.AsyncDB`
- Use `time.monotonic()` for execution time measurement
- SQLite metadata uses `PRAGMA table_info()` not `information_schema`
- Each source resolves credentials via `self.resolve_credentials(credentials)` before use
- Add `self.logger` calls at key points (connection, query start/end, errors)
- Never execute DDL/DML — only SELECT-like queries

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` — existing query execution pattern
- `parrot/interfaces/database.py` — `get_default_credentials()` function

---

## Acceptance Criteria

- [ ] `PostgresSource` registered as `"pg"` in source registry
- [ ] `MySQLSource` registered as `"mysql"` in source registry
- [ ] `SQLiteSource` registered as `"sqlite"` in source registry
- [ ] All three inherit `validate_query()` from `AbstractDatabaseSource`
- [ ] `get_metadata()` returns `MetadataResult` with correct table/column info
- [ ] `query()` returns `QueryResult` with rows and execution_time_ms
- [ ] `query_row()` returns `RowResult` with single row or `found=False`
- [ ] `get_default_credentials()` delegates to `parrot.interfaces.database`
- [ ] All three importable: `from parrot.tools.database.sources.postgres import PostgresSource`

---

## Test Specification

```python
# tests/tools/database/test_sql_sources_core.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.tools.database.sources.postgres import PostgresSource
from parrot.tools.database.sources.mysql import MySQLSource
from parrot.tools.database.sources.sqlite import SQLiteSource
from parrot.tools.database.base import ValidationResult


class TestPostgresSource:
    def test_driver_and_dialect(self):
        src = PostgresSource()
        assert src.driver == "pg"
        assert src.sqlglot_dialect == "postgres"

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self):
        src = PostgresSource()
        result = await src.validate_query("SELECT 1")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_invalid_sql(self):
        src = PostgresSource()
        result = await src.validate_query("SELEC FROM")
        assert result.valid is False
        assert result.error is not None


class TestMySQLSource:
    def test_driver_and_dialect(self):
        src = MySQLSource()
        assert src.driver == "mysql"
        assert src.sqlglot_dialect == "mysql"


class TestSQLiteSource:
    def test_driver_and_dialect(self):
        src = SQLiteSource()
        assert src.driver == "sqlite"
        assert src.sqlglot_dialect == "sqlite"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/databasetoolkit.spec.md` for full context
2. **Check dependencies** — TASK-427 and TASK-428 must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-429-dbtoolkit-sql-sources-core.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
