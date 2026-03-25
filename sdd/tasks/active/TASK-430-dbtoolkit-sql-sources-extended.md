# TASK-430: Extended SQL Sources — BigQuery, Oracle, ClickHouse, DuckDB

**Feature**: DatabaseToolkit
**Feature ID**: FEAT-062
**Spec**: `sdd/specs/databasetoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-427, TASK-428
**Assigned-to**: unassigned

---

## Context

These four SQL sources follow the same pattern as the core SQL sources but have
driver-specific metadata queries and dialect differences. They can be implemented
in parallel with TASK-429 since both only depend on the base and registry.

Implements **Modules 7, 7b, 7c, 7d** from the spec.

---

## Scope

- Implement `BigQuerySource` — driver `"bigquery"`, sqlglot dialect `"bigquery"`.
  Metadata via BigQuery `INFORMATION_SCHEMA.COLUMNS`.
- Implement `OracleSource` — driver `"oracle"`, sqlglot dialect `"oracle"`.
  Metadata via `ALL_TAB_COLUMNS`.
- Implement `ClickHouseSource` — driver `"clickhouse"`, sqlglot dialect `"clickhouse"`.
  Metadata via `system.columns`.
- Implement `DuckDBSource` — driver `"duckdb"`, sqlglot dialect `"duckdb"`.
  Metadata via `information_schema.columns`. Support in-process mode (file path
  in credentials).
- Each source must register, implement all abstract methods, and follow the
  same pattern as TASK-429 sources.

**NOT in scope**: MSSQL (separate task due to stored procedure complexity),
non-SQL sources.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/sources/bigquery.py` | CREATE | BigQuerySource |
| `parrot/tools/database/sources/oracle.py` | CREATE | OracleSource |
| `parrot/tools/database/sources/clickhouse.py` | CREATE | ClickHouseSource |
| `parrot/tools/database/sources/duckdb.py` | CREATE | DuckDBSource |

---

## Implementation Notes

### Key Constraints
- Follow the exact same pattern as `PostgresSource` in TASK-429
- Each source sets appropriate `driver` and `sqlglot_dialect`
- BigQuery metadata query: `SELECT * FROM \`{dataset}.INFORMATION_SCHEMA.COLUMNS\``
- Oracle metadata query: `SELECT * FROM ALL_TAB_COLUMNS WHERE OWNER = :schema`
- ClickHouse metadata query: `SELECT * FROM system.columns WHERE database = :db`
- DuckDB: supports both file-based (`{"database": "/path/to/file.db"}`) and
  in-memory connections
- All use asyncdb for connections — the asyncdb driver handles the actual protocol

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` — `DriverInfo.DRIVER_MAP`
- TASK-429 sources — follow the same implementation pattern

---

## Acceptance Criteria

- [ ] `BigQuerySource` registered as `"bigquery"`, dialect `"bigquery"`
- [ ] `OracleSource` registered as `"oracle"`, dialect `"oracle"`
- [ ] `ClickHouseSource` registered as `"clickhouse"`, dialect `"clickhouse"`
- [ ] `DuckDBSource` registered as `"duckdb"`, dialect `"duckdb"`
- [ ] Each source's `get_metadata()` uses the correct driver-specific query
- [ ] Each source's `query()` and `query_row()` execute via asyncdb
- [ ] All importable from their respective modules

---

## Test Specification

```python
# tests/tools/database/test_sql_sources_extended.py
import pytest
from parrot.tools.database.sources.bigquery import BigQuerySource
from parrot.tools.database.sources.oracle import OracleSource
from parrot.tools.database.sources.clickhouse import ClickHouseSource
from parrot.tools.database.sources.duckdb import DuckDBSource


class TestBigQuerySource:
    def test_driver_and_dialect(self):
        src = BigQuerySource()
        assert src.driver == "bigquery"
        assert src.sqlglot_dialect == "bigquery"

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self):
        src = BigQuerySource()
        result = await src.validate_query("SELECT * FROM `project.dataset.table`")
        assert result.valid is True


class TestOracleSource:
    def test_driver_and_dialect(self):
        src = OracleSource()
        assert src.driver == "oracle"
        assert src.sqlglot_dialect == "oracle"


class TestClickHouseSource:
    def test_driver_and_dialect(self):
        src = ClickHouseSource()
        assert src.driver == "clickhouse"
        assert src.sqlglot_dialect == "clickhouse"


class TestDuckDBSource:
    def test_driver_and_dialect(self):
        src = DuckDBSource()
        assert src.driver == "duckdb"
        assert src.sqlglot_dialect == "duckdb"

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self):
        src = DuckDBSource()
        result = await src.validate_query("SELECT * FROM read_parquet('data.parquet')")
        assert result.valid is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/databasetoolkit.spec.md` for full context
2. **Check dependencies** — TASK-427 and TASK-428 must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-430-dbtoolkit-sql-sources-extended.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
