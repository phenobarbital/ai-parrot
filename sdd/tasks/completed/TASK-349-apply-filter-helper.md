# TASK-349: Implement _apply_filter Helper and add_dataset filter Parameter

**Feature**: DatasetManager add_dataset Filter Support
**Feature ID**: FEAT-050
**Spec**: `sdd/specs/add-filter-add-dataset.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Core implementation task for FEAT-050. Adds a `_apply_filter` static method to `DatasetManager` and a `filter` parameter to `add_dataset()`. The filter is applied to the fetched DataFrame after source execution but before registration via `add_dataframe()`.

---

## Scope

- Add a `_apply_filter(df, filter_dict)` static/private method to `DatasetManager` in `parrot/tools/dataset_manager/tool.py`.
  - Each key is a column name, each value is a scalar (equality) or list/tuple/set (isin).
  - All conditions are ANDed.
  - Raises `ValueError` if a column is not found in the DataFrame.
  - Returns `df.loc[mask].reset_index(drop=True)`.
- Add `filter: Optional[Dict[str, Any]] = None` parameter to `add_dataset()`.
- After `df` is obtained from any of the 4 source branches (dataframe, query_slug, query, table), apply:
  ```python
  if filter:
      df = self._apply_filter(df, filter)
  ```
- The filtered `df` is then passed to `self.add_dataframe()` as before.
- The confirmation message from `add_dataframe()` will automatically reflect the filtered shape.

**NOT in scope**: Tests (TASK-350), changes to DataSource classes, changes to `add_query()` or `add_table_source()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/tool.py` | MODIFY | Add `_apply_filter` method and `filter` param to `add_dataset()` |

---

## Implementation Notes

- The `filter` parameter name shadows the Python builtin — use `filter_dict` internally if needed, but keep the public API as `filter` for user ergonomics. Alternatively, name the parameter `filter` in the signature and rename internally.
- The method should be `@staticmethod` since it doesn't need `self`.
- Ensure the type hint imports `Dict` and `Any` from `typing` (already imported in the file).
- The filter is applied identically for all 4 source types since it operates on the resulting DataFrame.

---

## Acceptance Criteria

- [ ] `add_dataset(..., filter={"project": "Pokemon"})` registers only matching rows.
- [ ] `add_dataset(..., filter={"status": ["active", "pending"]})` uses isin matching.
- [ ] Multiple filter keys are ANDed together.
- [ ] Non-existent column raises `ValueError` with available columns listed.
- [ ] Omitting `filter` preserves existing behavior.
- [ ] Confirmation message reflects filtered DataFrame shape.
