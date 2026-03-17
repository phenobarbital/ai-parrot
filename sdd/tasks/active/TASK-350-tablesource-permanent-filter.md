# TASK-350 — TableSource Permanent Filter

**Feature**: FEAT-051 — add-filter-datasetmanager
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: —

---

## Objective

Add an optional `permanent_filter: Optional[Dict[str, Any]]` parameter to `TableSource` that injects a WHERE clause into every SQL query in `fetch()`.

## File(s) to Modify

- `parrot/tools/dataset_manager/sources/table.py`

## Implementation Details

1. **`__init__()` change**: Add `permanent_filter: Optional[Dict[str, Any]] = None` parameter. Store as `self._permanent_filter = permanent_filter or {}`.

2. **`_build_filter_clause()` new method**: Build a SQL WHERE fragment from the permanent filter dict.
   - Scalar values: `column = 'value'`
   - List/tuple values: `column IN ('a', 'b', 'c')`
   - Values must be safely escaped (reuse existing patterns or validate against injection).
   - Column names must be validated against `_SAFE_IDENTIFIER_RE` (e.g., `^[a-zA-Z_][a-zA-Z0-9_.]*$`).
   - Returns empty string if no permanent filter is set.

3. **`_inject_permanent_filter(sql)` new method**: Append the filter clause to SQL.
   - If SQL already contains `WHERE` (case-insensitive): append with `AND`.
   - If SQL has no `WHERE`: insert `WHERE <clause>` before any trailing `ORDER BY`, `GROUP BY`, `LIMIT`, or at the end.
   - Handle edge cases carefully; document that complex SQL (CTEs, subqueries) should embed filters manually.

4. **`fetch()` change**: After existing SQL validation, inject permanent filter:
   ```python
   if self._permanent_filter:
       sql = self._inject_permanent_filter(sql)
   ```

5. **`cache_key` property**: Same pattern as QuerySlugSource — append md5 hash suffix if filter is set.

6. **`describe()` method**: Append permanent filter info if set.

## Acceptance Criteria

- [ ] `TableSource(table="t", driver="pg", permanent_filter={"status": "active"})` stores the filter.
- [ ] `fetch()` appends `WHERE status = 'active'` to SQL.
- [ ] List values generate `column IN ('a', 'b')` syntax.
- [ ] Filter is safely escaped (no SQL injection via values).
- [ ] Correctly appends `AND` when SQL already has a WHERE clause.
- [ ] `cache_key` differs between filtered and unfiltered sources.
- [ ] `describe()` includes filter info.
- [ ] Omitting `permanent_filter` preserves existing behavior.

## Tests

- `test_table_permanent_filter_where` — WHERE clause generated from filter dict.
- `test_table_permanent_filter_and_existing_where` — AND appended to existing WHERE.
- `test_table_permanent_filter_list_values` — IN clause for list values.
- `test_table_permanent_filter_escaping` — dangerous values safely escaped.
- `test_table_permanent_filter_cache_key` — filtered source has different cache_key.
- `test_table_no_permanent_filter_compat` — omitting permanent_filter works as before.
