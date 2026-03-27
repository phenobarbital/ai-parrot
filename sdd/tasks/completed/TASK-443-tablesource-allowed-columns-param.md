# TASK-443: TableSource — allowed_columns parameter and schema filtering

**Feature**: datasetmanager-tablesource-column-list
**Spec**: `sdd/specs/datasetmanager-tablesource-column-list.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-061. It adds the `allowed_columns` parameter to `TableSource`, validates column names, filters the prefetched schema to only include allowed columns, updates `describe()` to mention restrictions, and incorporates `allowed_columns` into `cache_key`.

Implements Spec Module 1.

---

## Scope

- Add `allowed_columns: Optional[List[str]] = None` parameter to `TableSource.__init__()`.
- Store as `self._allowed_columns` (private attribute).
- Add read-only `allowed_columns` property.
- Validate each column name in `allowed_columns` against `_SAFE_IDENTIFIER_RE` (reuse `_validate_identifier()`). Raise `ValueError` on invalid names.
- In `prefetch_schema()`, after fetching full schema, filter `self._schema` to only keys present in `allowed_columns` (when set).
  - If `strict_schema=True` and an allowed column is NOT found in the actual schema, raise `ValueError` listing the missing columns.
  - If `strict_schema=False`, log a warning for missing columns and continue with only the found ones.
- Update `describe()`:
  - When `allowed_columns` is set, append: `" [restricted to N columns: col1, col2, ...]"`.
  - Add text: `"Only these columns may be used in queries."`.
- Update `cache_key` property:
  - When `allowed_columns` is set, append `:ac={hash}` where hash is MD5[:8] of the sorted JSON-encoded list (same pattern as `permanent_filter`).

**NOT in scope**: SQL validation in `fetch()` (TASK-423), DatasetManager passthrough (TASK-424), tests (TASK-425/426).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py` | MODIFY | Add `allowed_columns` param, schema filtering, describe update, cache_key update |

---

## Implementation Notes

### Pattern to Follow

Follow the `permanent_filter` pattern already in `TableSource.__init__()`:

```python
# Existing pattern for permanent_filter (line 152):
self._permanent_filter: Dict[str, Any] = permanent_filter or {}
# Validate filter column names early
for col_name in self._permanent_filter:
    _validate_identifier(col_name, 'permanent_filter column')

# New pattern for allowed_columns:
self._allowed_columns: Optional[List[str]] = None
if allowed_columns is not None:
    for col_name in allowed_columns:
        _validate_identifier(col_name, 'allowed_columns entry')
    self._allowed_columns = list(allowed_columns)  # defensive copy
```

### Schema filtering in prefetch_schema()

After the existing schema population logic (line ~392-395), add filtering:

```python
# Filter schema to allowed columns
if self._allowed_columns is not None:
    full_schema = dict(self._schema)
    self._schema = {
        col: dtype for col, dtype in full_schema.items()
        if col in self._allowed_columns
    }
    missing = set(self._allowed_columns) - set(full_schema.keys())
    if missing:
        if self.strict_schema:
            raise ValueError(
                f"allowed_columns contains columns not found in table "
                f"'{self.table}': {sorted(missing)}"
            )
        else:
            logger.warning(
                "TableSource('%s'): allowed_columns not found in schema: %s",
                self.table, sorted(missing),
            )
```

### cache_key pattern

```python
# After existing permanent_filter cache key logic:
if self._allowed_columns is not None:
    ac_suffix = hashlib.md5(
        json.dumps(sorted(self._allowed_columns)).encode()
    ).hexdigest()[:8]
    base = f"{base}:ac={ac_suffix}"
```

### Key Constraints
- `allowed_columns=None` means NO restriction (existing behavior, unchanged).
- `allowed_columns=[]` (empty list) should raise `ValueError` — an empty restriction makes no sense.
- Column names are case-sensitive (matching DB behavior).

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py` — the file to modify
- `_validate_identifier()` at line 37 — reuse for column validation
- `_SAFE_IDENTIFIER_RE` at line 34 — regex for safe identifiers

---

## Acceptance Criteria

- [ ] `TableSource` accepts `allowed_columns` parameter
- [ ] Invalid column names raise `ValueError`
- [ ] Empty `allowed_columns` list raises `ValueError`
- [ ] `prefetch_schema()` filters `_schema` to allowed columns only
- [ ] Missing allowed columns handled per `strict_schema` setting
- [ ] `describe()` mentions column restriction with list
- [ ] `cache_key` incorporates `allowed_columns` hash
- [ ] `allowed_columns=None` preserves all existing behavior exactly

---

## Test Specification

```python
# Tests will be in TASK-425, but here's what must pass:
import pytest
from parrot.tools.dataset_manager.sources.table import TableSource

def test_allowed_columns_stored():
    ts = TableSource(table="public.t", driver="pg", allowed_columns=["id", "name"])
    assert ts.allowed_columns == ["id", "name"]

def test_allowed_columns_none_default():
    ts = TableSource(table="public.t", driver="pg")
    assert ts.allowed_columns is None

def test_allowed_columns_invalid_name():
    with pytest.raises(ValueError, match="allowed_columns entry"):
        TableSource(table="public.t", driver="pg", allowed_columns=["id; DROP TABLE"])

def test_allowed_columns_empty_list():
    with pytest.raises(ValueError):
        TableSource(table="public.t", driver="pg", allowed_columns=[])
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-tablesource-column-list.spec.md`
2. **Check dependencies** — none for this task
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py` fully
5. **Implement** following the scope and notes above
6. **Verify** by running: `source .venv/bin/activate && python -c "from parrot.tools.dataset_manager.sources.table import TableSource; ts = TableSource('public.t', 'pg', allowed_columns=['id']); print(ts.allowed_columns)"`
7. **Move this file** to `sdd/tasks/completed/TASK-443-tablesource-allowed-columns-param.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
