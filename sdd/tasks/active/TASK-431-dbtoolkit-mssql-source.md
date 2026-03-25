# TASK-431: MSSQL Source with Stored Procedure Support

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

MSSQL is a SQL source but has a unique requirement: it must support executing stored
procedures via `EXEC`/`EXECUTE` statements. The base `validate_query()` using sqlglot
may reject these statements, so `MSSQLSource` must override validation to allow them
alongside standard SELECT queries.

Implements **Module 7a** from the spec.

---

## Scope

- Implement `MSSQLSource` — driver `"mssql"`, sqlglot dialect `"tsql"`.
- Override `validate_query()` to:
  - Use sqlglot with `"tsql"` dialect for standard SQL.
  - Additionally accept `EXEC`/`EXECUTE` statements (regex-based pre-check
    before sqlglot validation).
- Implement `get_metadata()` that queries both `INFORMATION_SCHEMA.COLUMNS`
  AND `sys.procedures` to include stored procedures in the metadata result.
- Implement `query()` that can handle both SELECT statements and `EXEC` calls.
- Implement `query_row()` for single-row results.

**NOT in scope**: Other SQL sources, non-SQL sources.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/sources/mssql.py` | CREATE | MSSQLSource with stored proc support |

---

## Implementation Notes

### Pattern to Follow
```python
import re
from parrot.tools.database.base import AbstractDatabaseSource, ValidationResult
from parrot.tools.database.sources import register_source

_EXEC_PATTERN = re.compile(
    r"^\s*(EXEC|EXECUTE)\s+", re.IGNORECASE
)

@register_source("mssql")
class MSSQLSource(AbstractDatabaseSource):
    driver = "mssql"
    sqlglot_dialect = "tsql"

    async def validate_query(self, query: str) -> ValidationResult:
        # If it's an EXEC statement, validate structure separately
        if _EXEC_PATTERN.match(query):
            return ValidationResult(valid=True, dialect="tsql")
        # Otherwise delegate to base sqlglot validation
        return await super().validate_query(query)

    async def get_metadata(self, credentials, tables=None):
        # Query INFORMATION_SCHEMA.COLUMNS for tables
        # Also query sys.procedures for stored procedures
        # Return stored procs as TableMeta entries with schema_name="procedures"
        ...
```

### Key Constraints
- `EXEC`/`EXECUTE` must be validated as a valid query type — not blocked
- `sys.procedures` results should be included in metadata with a distinguishing
  marker (e.g., `schema_name="stored_procedures"`)
- The stored procedure metadata should include procedure name and parameters
  if discoverable from `sys.parameters`
- Standard SELECT queries must still be validated via sqlglot tsql dialect
- Connection via asyncdb uses driver `"mssql"`

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` — `QueryValidator.validate_sql_query()`
  blocks `EXEC`/`EXECUTE` — we want to allow them here

---

## Acceptance Criteria

- [ ] `MSSQLSource` registered as `"mssql"` in source registry
- [ ] `validate_query("SELECT 1")` returns `valid=True` via tsql dialect
- [ ] `validate_query("EXEC sp_who")` returns `valid=True`
- [ ] `validate_query("EXECUTE dbo.GetUsers @age = 25")` returns `valid=True`
- [ ] `validate_query("SELEC FROM")` returns `valid=False`
- [ ] `get_metadata()` returns both tables and stored procedures
- [ ] `query("EXEC sp_name")` executes stored procedure via asyncdb
- [ ] Import works: `from parrot.tools.database.sources.mssql import MSSQLSource`

---

## Test Specification

```python
# tests/tools/database/test_mssql_source.py
import pytest
from parrot.tools.database.sources.mssql import MSSQLSource


class TestMSSQLSource:
    def test_driver_and_dialect(self):
        src = MSSQLSource()
        assert src.driver == "mssql"
        assert src.sqlglot_dialect == "tsql"

    @pytest.mark.asyncio
    async def test_validate_select(self):
        src = MSSQLSource()
        result = await src.validate_query("SELECT TOP 10 * FROM users")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_exec(self):
        src = MSSQLSource()
        result = await src.validate_query("EXEC sp_who")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_execute_with_params(self):
        src = MSSQLSource()
        result = await src.validate_query(
            "EXECUTE dbo.GetUsers @age = 25, @status = 'active'"
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_invalid_sql(self):
        src = MSSQLSource()
        result = await src.validate_query("SELEC FROM")
        assert result.valid is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/databasetoolkit.spec.md` for full context
2. **Check dependencies** — TASK-427 and TASK-428 must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-431-dbtoolkit-mssql-source.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
