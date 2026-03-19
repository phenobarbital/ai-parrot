# Feature Specification: DatasetManager add_dataset Filter Support

**Feature ID**: FEAT-050
**Date**: 2026-03-17
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The `DatasetManager.add_dataset()` method (in `parrot/tools/dataset_manager/tool.py`) eagerly fetches data from a source (query_slug, raw SQL, table, or pre-loaded DataFrame) and registers the full result as an in-memory DataFrame. There is currently **no way to apply row-level filtering at registration time** without either:

1. Writing a custom SQL WHERE clause (only works for SQL/table sources), or
2. Fetching the entire dataset, then filtering in `python_repl_pandas` and calling `store_dataframe()`.

Both approaches require extra steps from the LLM or the caller. A simple, source-agnostic `filter` parameter (e.g. `filter={"project": "Pokemon"}`) would let callers declaratively reduce the DataFrame **before** it is registered in the catalog — reducing memory usage and giving the LLM a cleaner, pre-scoped dataset.

### Goals

- Add an optional `filter: Optional[Dict[str, Any]]` parameter to `add_dataset()`.
- Apply the filter to the fetched DataFrame **after** source execution but **before** registration via `add_dataframe()`.
- Support simple equality matching: each key is a column name, each value is the required value (or a list of allowed values for `isin`-style matching).
- Ensure the filter works identically regardless of the data source (query_slug, query, table, dataframe).
- Maintain full backward compatibility — omitting `filter` preserves current behavior.

### Non-Goals (explicitly out of scope)

- Complex filter expressions (greater-than, less-than, regex, compound AND/OR logic)
- Filter pushdown into SQL queries or BigQuery (optimization for a future iteration)
- Filtering support in lazy `add_query()` or `add_table_source()` methods
- UI or LLM prompt changes for filter discovery

---

## 2. Architectural Design

### Overview

The change is minimal and localized. A single `filter` parameter is added to `add_dataset()`. After the DataFrame `df` is obtained from any source, a filtering step is applied before calling `self.add_dataframe()`.

```
Source fetch → df (full) → apply_filter(df, filter) → df (filtered) → add_dataframe()
```

### Filter Logic

```python
def _apply_filter(df: pd.DataFrame, filter: Dict[str, Any]) -> pd.DataFrame:
    """Apply dictionary-based equality filters to a DataFrame.

    Each key is a column name. Each value is either:
    - A scalar: rows where column == value are kept.
    - A list/tuple/set: rows where column value is in the collection are kept.

    All conditions are ANDed together.
    """
    mask = pd.Series(True, index=df.index)
    for col, value in filter.items():
        if col not in df.columns:
            raise ValueError(f"Filter column '{col}' not found in DataFrame. Available: {list(df.columns)}")
        if isinstance(value, (list, tuple, set)):
            mask &= df[col].isin(value)
        else:
            mask &= df[col] == value
    return df.loc[mask].reset_index(drop=True)
```

### Affected Components

| Component | File | Change |
|-----------|------|--------|
| `DatasetManager.add_dataset()` | `parrot/tools/dataset_manager/tool.py` | Add `filter` param, call `_apply_filter` before `add_dataframe` |
| `_apply_filter()` (new helper) | `parrot/tools/dataset_manager/tool.py` | Private method on DatasetManager or module-level function |

### Integration Points

- No changes to `DataSource` ABC or any source implementations.
- No changes to `DatasetEntry`, `add_dataframe()`, or caching.
- The filter is applied in-memory on the already-fetched pandas DataFrame.

---

## 3. Implementation Plan

### Phase 1: Core Filter Implementation

1. Add `_apply_filter` static/private method to `DatasetManager`.
2. Add `filter: Optional[Dict[str, Any]] = None` parameter to `add_dataset()`.
3. After the `df` is obtained (from any of the 4 source branches), apply:
   ```python
   if filter:
       df = self._apply_filter(df, filter)
   ```
4. The filtered `df` is then passed to `self.add_dataframe()` as before.

### Phase 2: Testing

1. Unit tests for `_apply_filter` with scalar values, list values, missing columns.
2. Integration test for `add_dataset(dataframe=..., filter=...)`.
3. Integration test for `add_dataset(table=..., filter=...)` (if test DB available).

---

## 4. Acceptance Criteria

- [ ] `add_dataset(..., filter={"project": "Pokemon"})` registers only rows where `project == "Pokemon"`.
- [ ] `add_dataset(..., filter={"status": ["active", "pending"]})` registers only rows where `status` is in the list.
- [ ] Multiple filter keys are ANDed: `filter={"project": "Pokemon", "status": "active"}` keeps only rows matching both.
- [ ] Filtering on a non-existent column raises `ValueError` with a clear message.
- [ ] Omitting `filter` (default `None`) preserves existing behavior — no regression.
- [ ] The confirmation message reflects the **filtered** DataFrame shape.
- [ ] Works with all four source types: `dataframe`, `query_slug`, `query`, `table`.

---

## 5. Testing Strategy

### Unit Tests

| Test | Description |
|------|-------------|
| `test_apply_filter_scalar` | Single key, scalar value — rows filtered correctly |
| `test_apply_filter_list` | Single key, list value — isin matching works |
| `test_apply_filter_multiple_keys` | Multiple keys ANDed together |
| `test_apply_filter_empty_result` | Filter that matches no rows returns empty DataFrame |
| `test_apply_filter_missing_column` | Non-existent column raises ValueError |
| `test_apply_filter_none` | None filter returns DataFrame unchanged |

### Integration Tests

| Test | Description |
|------|-------------|
| `test_add_dataset_with_filter` | `add_dataset(dataframe=df, filter=...)` registers filtered data |
| `test_add_dataset_no_filter_backward_compat` | Existing calls without filter still work |

---

## 6. Dependencies

- **pandas**: Already a core dependency — no new packages needed.
- **FEAT-030** (DatasetManager Lazy Data Sources): Already implemented. This feature builds on the current `add_dataset()` signature.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Filter applied after full fetch — no memory savings during fetch | Medium | Low | Document that filter reduces registered size, not fetch size. SQL-level pushdown is a future optimization. |
| Type mismatch in filter values (e.g., string "1" vs int 1) | Medium | Low | Pandas handles coercion; document that filter values should match column dtypes. |

---

## 8. Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree).
- **Reason**: Small feature, 2-3 tasks max, no parallelization benefit.
- **Cross-feature dependencies**: None — this is additive to the existing `add_dataset()` API.
