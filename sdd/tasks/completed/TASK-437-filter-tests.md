# TASK-437: Unit and Integration Tests for add_dataset Filter

**Feature**: DatasetManager add_dataset Filter Support
**Feature ID**: FEAT-050
**Spec**: `sdd/specs/add-filter-add-dataset.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-349
**Assigned-to**: unassigned

---

## Context

> Test task for FEAT-050. Validates the `_apply_filter` helper and the `filter` parameter on `add_dataset()` with unit tests for the filter logic and integration tests for the full add_dataset flow.

---

## Scope

- Create test file `tests/tools/test_dataset_filter.py` (or add to existing dataset manager test file if one exists).
- Unit tests for `_apply_filter`:
  - `test_apply_filter_scalar`: Single key, scalar value filters correctly.
  - `test_apply_filter_list`: Single key, list value uses isin matching.
  - `test_apply_filter_tuple`: Single key, tuple value uses isin matching.
  - `test_apply_filter_set`: Single key, set value uses isin matching.
  - `test_apply_filter_multiple_keys`: Multiple keys ANDed together.
  - `test_apply_filter_empty_result`: Filter matching no rows returns empty DataFrame with correct columns.
  - `test_apply_filter_missing_column`: Non-existent column raises `ValueError`.
  - `test_apply_filter_none_noop`: `None` or empty dict filter returns DataFrame unchanged.
- Integration tests for `add_dataset` with filter:
  - `test_add_dataset_dataframe_with_filter`: Pass a DataFrame and filter, verify only matching rows registered.
  - `test_add_dataset_no_filter_backward_compat`: Verify existing calls without filter still work.

**NOT in scope**: Tests requiring database connections (query_slug, table modes), changes to implementation code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/test_dataset_filter.py` | CREATE | Unit + integration tests for filter functionality |

---

## Implementation Notes

- Use `pytest` and `pytest-asyncio` for async tests.
- Create sample DataFrames with `pd.DataFrame` for unit tests — no external dependencies needed.
- For the integration test with `add_dataset(dataframe=...)`, instantiate `DatasetManager` directly and call `add_dataset` with a pre-built DataFrame.
- Check that the registered dataset (via `get_dataframe()` or similar) contains only the filtered rows.

---

## Acceptance Criteria

- [ ] All unit tests pass for scalar, list, tuple, set, multiple keys, empty result, missing column, and None filter.
- [ ] Integration test confirms `add_dataset(dataframe=df, filter=...)` registers only filtered rows.
- [ ] Backward compatibility test confirms no regression when `filter` is omitted.
- [ ] `pytest tests/tools/test_dataset_filter.py` passes cleanly.
