# TASK-446: Unit tests for TableSource allowed_columns

**Feature**: datasetmanager-tablesource-column-list
**Spec**: `sdd/specs/datasetmanager-tablesource-column-list.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-422, TASK-423, TASK-424
**Assigned-to**: unassigned

---

## Context

All implementation tasks (TASK-422/423/424) are complete. This task adds comprehensive unit tests covering the `allowed_columns` feature in `TableSource` and the `add_table_source()` passthrough.

Implements Spec Module 4 (unit tests).

---

## Scope

- Create test file `packages/ai-parrot/tests/tools/test_tablesource_allowed_columns.py`.
- Test all acceptance criteria from the spec:
  - Parameter storage and property access
  - Column name validation (valid and invalid)
  - Empty list rejection
  - Schema filtering after prefetch
  - Missing columns handling (strict vs lenient)
  - `describe()` output with restrictions
  - `cache_key` with and without `allowed_columns`
  - `fetch()` rejecting `SELECT *`
  - `fetch()` rejecting disallowed columns
  - `fetch()` allowing valid columns
  - Post-fetch DataFrame column filtering
  - `allowed_columns=None` preserving existing behavior
  - `add_table_source()` passthrough

**NOT in scope**: Integration tests with actual database connections (TASK-426).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/test_tablesource_allowed_columns.py` | CREATE | Comprehensive unit tests |

---

## Implementation Notes

### Pattern to Follow

Look at existing test patterns in the project. Use `pytest` with `pytest-asyncio` for async tests. Mock `_run_query` to avoid database connections.

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.tools.dataset_manager.sources.table import TableSource


@pytest.fixture
def restricted_source():
    """TableSource with allowed_columns restriction."""
    ts = TableSource(
        table="public.employees",
        driver="pg",
        allowed_columns=["id", "name", "department"],
    )
    return ts


@pytest.fixture
def unrestricted_source():
    """TableSource without allowed_columns (baseline)."""
    return TableSource(table="public.employees", driver="pg")


@pytest.fixture
def full_schema():
    """Simulated full schema from INFORMATION_SCHEMA."""
    return {
        "id": "integer",
        "name": "varchar",
        "department": "varchar",
        "salary": "numeric",
        "ssn": "varchar",
        "password_hash": "varchar",
    }
```

### Test categories

1. **Construction tests**: valid/invalid column names, empty list, None default
2. **Schema filtering tests**: mock `_run_query` in `prefetch_schema`, verify `_schema` is filtered
3. **Describe tests**: verify output text
4. **Cache key tests**: verify different hashes for different allowed_columns
5. **Fetch validation tests**: mock `_run_query`, test SQL rejection/acceptance
6. **Post-fetch filter tests**: mock `_run_query` returning extra columns
7. **Backward compatibility tests**: `allowed_columns=None` behaves identically

### Key Constraints
- All database calls must be mocked — no real connections
- Use `pytest.mark.asyncio` for async test methods
- Test error messages contain actionable information (allowed column list)

### References in Codebase
- `packages/ai-parrot/tests/tools/` — existing test location
- Look for existing `test_tablesource*.py` or similar for patterns

---

## Acceptance Criteria

- [ ] Test file created at correct path
- [ ] All 14+ tests from spec Test Specification are implemented
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_tablesource_allowed_columns.py -v`
- [ ] No real database connections (all mocked)
- [ ] Tests cover both positive (valid) and negative (rejection) cases
- [ ] Tests verify error messages are actionable

---

## Test Specification

```python
class TestAllowedColumnsConstruction:
    def test_allowed_columns_stored(self): ...
    def test_allowed_columns_none_default(self): ...
    def test_allowed_columns_validated(self): ...
    def test_allowed_columns_empty_list_rejected(self): ...
    def test_allowed_columns_property(self): ...

class TestSchemaFiltering:
    async def test_schema_filtered_to_allowed(self): ...
    async def test_schema_missing_allowed_column_strict(self): ...
    async def test_schema_missing_allowed_column_lenient(self): ...

class TestDescribe:
    def test_describe_mentions_restriction(self): ...
    def test_describe_no_restriction_when_none(self): ...

class TestCacheKey:
    def test_cache_key_includes_allowed_columns(self): ...
    def test_cache_key_none_unchanged(self): ...
    def test_cache_key_different_columns_different_key(self): ...

class TestFetchValidation:
    async def test_fetch_rejects_select_star(self): ...
    async def test_fetch_allows_count_star(self): ...
    async def test_fetch_rejects_disallowed_column(self): ...
    async def test_fetch_allows_valid_columns(self): ...
    async def test_fetch_filters_dataframe_columns(self): ...
    async def test_no_restriction_unchanged_behavior(self): ...

class TestAddTableSourcePassthrough:
    async def test_add_table_source_passes_allowed_columns(self): ...
    async def test_add_table_source_default_none(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-tablesource-column-list.spec.md`
2. **Check dependencies** — TASK-422, TASK-423, TASK-424 must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** the implemented code in `table.py` and `tool.py` to understand exact signatures
5. **Create** the test file following the specification above
6. **Run tests**: `source .venv/bin/activate && pytest packages/ai-parrot/tests/tools/test_tablesource_allowed_columns.py -v`
7. **Fix** any failures until all tests pass
8. **Move this file** to `sdd/tasks/completed/TASK-446-tablesource-allowed-columns-unit-tests.md`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
