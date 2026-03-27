# TASK-445: DatasetManager — pass allowed_columns through to TableSource

**Feature**: datasetmanager-tablesource-column-list
**Spec**: `sdd/specs/datasetmanager-tablesource-column-list.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-422
**Assigned-to**: unassigned

---

## Context

The `allowed_columns` parameter is implemented in `TableSource` (TASK-422). This task threads it through `DatasetManager.add_table_source()` so users can pass `allowed_columns` when registering a table source via the public API.

Implements Spec Module 3.

---

## Scope

- Add `allowed_columns: Optional[List[str]] = None` parameter to `DatasetManager.add_table_source()`.
- Pass it through to the `TableSource(...)` constructor call.
- Update the registration log message to mention column restriction when `allowed_columns` is set.
- Update the return string to indicate column restriction (e.g. `"registered (5 columns, pg, restricted to 3 allowed columns)"`).

**NOT in scope**: TableSource internals (TASK-422/423), tests (TASK-425/426).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Add `allowed_columns` to `add_table_source()` signature and pass through |

---

## Implementation Notes

### Pattern to Follow

Look at how `permanent_filter` is passed through in `add_table_source()`:

```python
# Existing pattern (find the TableSource constructor call):
source = TableSource(
    table=table,
    driver=driver,
    dsn=dsn,
    credentials=credentials,
    strict_schema=strict_schema,
    permanent_filter=permanent_filter,
    # ADD: allowed_columns=allowed_columns,
)
```

### Registration message update

```python
# Existing message pattern:
# f"Table source '{name}' registered ({n_cols} columns, {driver}{row_info})."

# When allowed_columns is set, add restriction info:
col_info = f", restricted to {len(allowed_columns)} allowed columns" if allowed_columns else ""
return f"Table source '{name}' registered ({n_cols} columns, {driver}{row_info}{col_info})."
```

### Key Constraints
- The parameter must be optional with default `None` — no breaking changes.
- Parameter ordering: place `allowed_columns` after `permanent_filter` for consistency.

### References in Codebase
- `add_table_source()` method in `tool.py` — search for `async def add_table_source`
- `TableSource` constructor call within that method

---

## Acceptance Criteria

- [ ] `add_table_source()` accepts `allowed_columns` parameter
- [ ] Parameter is passed through to `TableSource` constructor
- [ ] Registration log/return message mentions restriction when set
- [ ] Omitting `allowed_columns` produces identical behavior to before

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

class TestAddTableSourceAllowedColumns:
    async def test_passes_allowed_columns_to_table_source(self):
        """add_table_source creates TableSource with allowed_columns."""
        # Mock TableSource, verify allowed_columns kwarg is passed
        ...

    async def test_no_allowed_columns_default(self):
        """Omitting allowed_columns passes None to TableSource."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-tablesource-column-list.spec.md`
2. **Check dependencies** — TASK-422 must be completed first
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — find `add_table_source()` method
5. **Implement** the passthrough changes
6. **Verify** by checking the method signature and constructor call
7. **Move this file** to `sdd/tasks/completed/TASK-445-datasetmanager-allowed-columns-passthrough.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
