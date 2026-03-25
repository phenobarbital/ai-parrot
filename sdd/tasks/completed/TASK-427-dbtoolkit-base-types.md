# TASK-427: Result Types & AbstractDatabaseSource

**Feature**: DatabaseToolkit
**Feature ID**: FEAT-062
**Spec**: `sdd/specs/databasetoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for the DatabaseToolkit feature. It defines all Pydantic
result models and the `AbstractDatabaseSource` abstract base class that every database
source must implement. All other tasks depend on this one.

Implements **Module 1** from the spec.

---

## Scope

- Implement all Pydantic v2 result models: `ValidationResult`, `ColumnMeta`,
  `TableMeta`, `MetadataResult`, `QueryResult`, `RowResult`.
- Implement `AbstractDatabaseSource` ABC with:
  - `driver: str` class attribute
  - `sqlglot_dialect: str | None` class attribute
  - `async resolve_credentials(credentials)` — explicit > default
  - `async get_default_credentials()` — abstract
  - `async validate_query(query)` — default implementation using sqlglot;
    raises `NotImplementedError` if `sqlglot_dialect is None`
  - `async get_metadata(credentials, tables)` — abstract
  - `async query(credentials, sql, params)` — abstract
  - `async query_row(credentials, sql, params)` — abstract
- Create the `parrot/tools/database/` package directory with `__init__.py` stub.

**NOT in scope**: Source implementations, registry, toolkit tools, tests beyond
basic model validation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/__init__.py` | CREATE | Empty stub (populated in TASK-435) |
| `parrot/tools/database/base.py` | CREATE | Result models + AbstractDatabaseSource |

---

## Implementation Notes

### Pattern to Follow
```python
from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel, Field

class ValidationResult(BaseModel):
    valid: bool
    error: str | None = None
    dialect: str | None = None

# ... other result models per spec section 2 "Data Models"

class AbstractDatabaseSource(ABC):
    driver: str
    sqlglot_dialect: str | None = None

    async def resolve_credentials(
        self, credentials: dict[str, Any] | None
    ) -> dict[str, Any]:
        return credentials or await self.get_default_credentials()

    @abstractmethod
    async def get_default_credentials(self) -> dict[str, Any]: ...

    async def validate_query(self, query: str) -> ValidationResult:
        if self.sqlglot_dialect is None:
            raise NotImplementedError(...)
        import sqlglot
        # ... see spec section 4 for full implementation
```

### Key Constraints
- All models must be Pydantic v2 (`BaseModel` from `pydantic`)
- Use `from __future__ import annotations` for forward references
- `sqlglot` is imported lazily inside `validate_query()` only
- No asyncdb import in this file — that belongs to source implementations

### References in Codebase
- `parrot/tools/abstract.py` — `AbstractTool`, `ToolResult`, `AbstractToolArgsSchema`
- `parrot/tools/dataset_manager/tool.py` — toolkit pattern reference
- `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` — existing `DriverInfo`

---

## Acceptance Criteria

- [ ] All 6 result models instantiate and serialize correctly
- [ ] `AbstractDatabaseSource` cannot be instantiated directly (ABC)
- [ ] `validate_query()` with `sqlglot_dialect` set validates SQL via sqlglot
- [ ] `validate_query()` with `sqlglot_dialect = None` raises `NotImplementedError`
- [ ] `resolve_credentials()` returns explicit creds when provided
- [ ] Import works: `from parrot.tools.database.base import AbstractDatabaseSource`

---

## Test Specification

```python
# tests/tools/database/test_base_types.py
import pytest
from parrot.tools.database.base import (
    ValidationResult, ColumnMeta, TableMeta,
    MetadataResult, QueryResult, RowResult,
    AbstractDatabaseSource,
)


class TestResultModels:
    def test_validation_result_valid(self):
        r = ValidationResult(valid=True, dialect="postgres")
        assert r.valid is True
        assert r.error is None

    def test_validation_result_invalid(self):
        r = ValidationResult(valid=False, error="parse error", dialect="postgres")
        assert r.valid is False
        assert "parse" in r.error

    def test_column_meta_defaults(self):
        c = ColumnMeta(name="id", data_type="integer")
        assert c.nullable is True
        assert c.primary_key is False
        assert c.default is None

    def test_table_meta_with_columns(self):
        t = TableMeta(
            name="users",
            schema_name="public",
            columns=[ColumnMeta(name="id", data_type="int", primary_key=True)],
        )
        assert len(t.columns) == 1
        assert t.columns[0].primary_key is True

    def test_query_result_fields(self):
        r = QueryResult(
            driver="pg", rows=[{"id": 1}], row_count=1,
            columns=["id"], execution_time_ms=12.5,
        )
        assert r.row_count == 1

    def test_row_result_not_found(self):
        r = RowResult(driver="pg", row=None, found=False, execution_time_ms=1.0)
        assert r.found is False
        assert r.row is None


class TestAbstractDatabaseSource:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            AbstractDatabaseSource()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/databasetoolkit.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-427-dbtoolkit-base-types.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-03-25
**Notes**: Implemented all 6 result models and AbstractDatabaseSource ABC. sqlglot validation works correctly with dialect-aware parsing.

**Deviations from spec**: none
