# TASK-444: TableSource — SQL column validation in fetch()

**Feature**: datasetmanager-tablesource-column-list
**Spec**: `sdd/specs/datasetmanager-tablesource-column-list.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-422
**Assigned-to**: unassigned

---

## Context

With `allowed_columns` stored and schema filtered (TASK-422), this task adds runtime enforcement in `fetch()`. The LLM-generated SQL must be validated to ensure it only references allowed columns, and `SELECT *` must be rejected with an actionable error. A post-fetch DataFrame column filter provides defense-in-depth.

Implements Spec Module 2.

---

## Scope

- In `fetch()`, when `self._allowed_columns` is set:
  1. **Reject `SELECT *`**: Detect `SELECT *` (but NOT `COUNT(*)`, `SELECT COUNT(*)`, etc.) and raise `ValueError` with a message listing allowed columns.
  2. **Extract and validate columns**: Parse the SELECT clause to extract column references and validate against `_allowed_columns`. Reject queries referencing disallowed columns with an actionable error.
  3. **Post-fetch column filter**: After `_run_query()` returns a DataFrame, filter columns to only include those in `_allowed_columns` (intersection with actual DataFrame columns). This is defense-in-depth for cases the regex heuristic misses.
- When `self._allowed_columns is None`, all existing behavior is unchanged (no new code paths execute).

**NOT in scope**: The `allowed_columns` parameter itself (TASK-422), DatasetManager changes (TASK-424), tests (TASK-425/426).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py` | MODIFY | Add `_validate_column_access()` method, update `fetch()` |

---

## Implementation Notes

### SELECT * detection

```python
# Detect SELECT * but not COUNT(*), SUM(*), etc.
# Pattern: SELECT followed by optional whitespace then * not preceded by function name
_SELECT_STAR_RE = re.compile(
    r'\bSELECT\s+\*\s',
    re.IGNORECASE,
)

# But allow SELECT COUNT(*), SELECT SUM(*), etc.
# Check: if "SELECT *" is found, verify it's not inside a function call
```

Strategy: detect `SELECT\s+\*` but exclude cases where `*` is inside parentheses (aggregate functions). Simplest approach: check if the text between SELECT and FROM contains a bare `*` not inside `(...)`.

### Column extraction from SELECT clause

```python
def _validate_column_access(self, sql: str) -> None:
    """Validate that SQL only references allowed columns.

    Raises ValueError with actionable message if violations found.
    """
    if self._allowed_columns is None:
        return

    allowed_set = set(self._allowed_columns)

    # 1. Reject bare SELECT *
    # Extract text between SELECT and FROM
    select_match = re.search(r'\bSELECT\b(.*?)\bFROM\b', sql, re.IGNORECASE | re.DOTALL)
    if select_match:
        select_clause = select_match.group(1).strip()
        # Check for bare * (not inside parentheses like COUNT(*))
        # Remove parenthesized expressions first, then check for *
        cleaned = re.sub(r'\([^)]*\)', '', select_clause)
        if '*' in cleaned:
            raise ValueError(
                f"SELECT * is not allowed on '{self.table}'. "
                f"This table is restricted to specific columns. "
                f"Use: SELECT {', '.join(self._allowed_columns)} FROM {self.table}"
            )

    # 2. Extract column identifiers from SELECT clause
    # (heuristic — handles common LLM patterns)
    # ... extract identifiers and check against allowed_set
```

### Post-fetch DataFrame filter

```python
# After _run_query() returns df:
if self._allowed_columns is not None:
    allowed_set = set(self._allowed_columns)
    actual_cols = set(df.columns)
    keep = [c for c in df.columns if c in allowed_set]
    if keep:
        df = df[keep]
    # If no overlap (e.g. all aliases), return as-is — don't drop everything
```

### Key Constraints
- `COUNT(*)` must NOT be rejected — it's a function, not a column reference.
- `SELECT col1, COUNT(*) FROM ... GROUP BY col1` is valid.
- Column extraction is heuristic — expressions like `UPPER(col)` may not be caught. The post-fetch filter is the safety net.
- Error messages MUST include the list of allowed columns so the LLM can self-correct.

### References in Codebase
- `fetch()` method at line 470 — existing table-name validation pattern to follow
- `_inject_permanent_filter()` — called after column validation, before query execution

---

## Acceptance Criteria

- [ ] `SELECT * FROM table` is rejected with helpful error when `allowed_columns` is set
- [ ] `SELECT COUNT(*)` and other aggregate functions with `*` are NOT rejected
- [ ] SQL referencing a disallowed column raises `ValueError` with list of allowed columns
- [ ] SQL using only allowed columns passes validation
- [ ] Post-fetch DataFrame only contains allowed columns (defense-in-depth)
- [ ] When `allowed_columns=None`, fetch behavior is completely unchanged
- [ ] Error messages are actionable (include allowed column list)

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch
from parrot.tools.dataset_manager.sources.table import TableSource

@pytest.fixture
def restricted_source():
    ts = TableSource(
        table="public.employees", driver="pg",
        allowed_columns=["id", "name", "department"],
    )
    ts._schema = {"id": "integer", "name": "varchar", "department": "varchar"}
    return ts

class TestFetchColumnValidation:
    async def test_rejects_select_star(self, restricted_source):
        with pytest.raises(ValueError, match="SELECT \\* is not allowed"):
            await restricted_source.fetch(sql="SELECT * FROM public.employees")

    async def test_allows_count_star(self, restricted_source):
        # Should not raise for SELECT COUNT(*)
        # (will need mock for _run_query)
        ...

    async def test_rejects_disallowed_column(self, restricted_source):
        with pytest.raises(ValueError, match="salary"):
            await restricted_source.fetch(
                sql="SELECT id, salary FROM public.employees"
            )

    async def test_allows_valid_columns(self, restricted_source):
        # Mock _run_query, verify no ValueError raised
        ...

    async def test_post_fetch_filters_columns(self, restricted_source):
        # Mock _run_query returning extra columns, verify filtered
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-tablesource-column-list.spec.md`
2. **Check dependencies** — TASK-422 must be completed first
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py` fully (with TASK-422 changes)
5. **Implement** `_validate_column_access()` method and update `fetch()`
6. **Verify** no regressions: existing tests still pass
7. **Move this file** to `sdd/tasks/completed/TASK-444-tablesource-sql-column-validation.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
