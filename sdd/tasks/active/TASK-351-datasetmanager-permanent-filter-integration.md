# TASK-351 — DatasetManager Permanent Filter Integration

**Feature**: FEAT-051 — add-filter-datasetmanager
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: TASK-349, TASK-350

---

## Objective

Expose the `permanent_filter` parameter through `DatasetManager.add_query()`, `DatasetManager.add_table_source()`, and `DatasetManager.add_dataset()` (for `query_slug` and `table` modes), passing it through to the respective source constructors.

## File(s) to Modify

- `parrot/tools/dataset_manager/tool.py`

## Implementation Details

1. **`add_query()` change**: Add `permanent_filter: Optional[Dict[str, Any]] = None` parameter. Pass it to `QuerySlugSource(slug=..., permanent_filter=permanent_filter)`.

2. **`add_table_source()` change**: Add `permanent_filter: Optional[Dict[str, Any]] = None` parameter. Pass it to `TableSource(table=..., driver=..., permanent_filter=permanent_filter)`.

3. **`add_dataset()` change**: Add `permanent_filter: Optional[Dict[str, Any]] = None` parameter.
   - When `query_slug` mode: pass to `QuerySlugSource(slug=query_slug, permanent_filter=permanent_filter)`.
   - When `table` mode: pass to `TableSource(table=table, driver=driver, permanent_filter=permanent_filter)`.
   - When `dataframe` or `query` mode: ignore `permanent_filter` (or warn if provided — it has no effect on InMemorySource/SQLQuerySource).

4. **Tool schema/docstrings**: Update the docstrings and parameter descriptions for all three methods so that the LLM tool schema includes `permanent_filter` with a clear description.

## Acceptance Criteria

- [ ] `add_query(name="x", query_slug="s", permanent_filter={"k": "v"})` creates a QuerySlugSource with the filter.
- [ ] `add_table_source(name="x", table="t", driver="pg", permanent_filter={"k": "v"})` creates a TableSource with the filter.
- [ ] `add_dataset(name="x", query_slug="s", permanent_filter={"k": "v"})` propagates to QuerySlugSource.
- [ ] `add_dataset(name="x", table="t", driver="pg", permanent_filter={"k": "v"})` propagates to TableSource.
- [ ] Omitting `permanent_filter` preserves existing behavior across all methods.
- [ ] Tool docstrings describe the parameter clearly.

## Tests

- `test_add_query_with_permanent_filter` — filter propagated to source.
- `test_add_table_source_with_permanent_filter` — filter propagated to source.
- `test_add_dataset_query_slug_permanent_filter` — filter propagated via add_dataset.
- `test_add_dataset_table_permanent_filter` — filter propagated via add_dataset.
- `test_add_dataset_no_filter_compat` — existing behavior preserved.
