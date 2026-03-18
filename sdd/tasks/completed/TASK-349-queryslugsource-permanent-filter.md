# TASK-349 — QuerySlugSource Permanent Filter

**Feature**: FEAT-051 — add-filter-datasetmanager
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: —

---

## Objective

Add an optional `permanent_filter: Optional[Dict[str, Any]]` parameter to `QuerySlugSource` that is merged into every `fetch()` call, with the permanent filter taking precedence over runtime params.

## File(s) to Modify

- `parrot/tools/dataset_manager/sources/query_slug.py`

## Implementation Details

1. **`__init__()` change**: Add `permanent_filter: Optional[Dict[str, Any]] = None` parameter. Store as `self._permanent_filter = permanent_filter or {}`.

2. **`fetch()` change**: Before passing conditions to QS, merge permanent filter into params:
   ```python
   merged = {**params, **self._permanent_filter}
   ```
   This ensures permanent keys override any runtime keys.

3. **`prefetch_schema()` change**: Include `self._permanent_filter` in the QS conditions used for schema prefetch so the schema reflects filtered data.

4. **`cache_key` property**: If `_permanent_filter` is non-empty, append a hash suffix:
   ```python
   suffix = hashlib.md5(json.dumps(self._permanent_filter, sort_keys=True).encode()).hexdigest()[:8]
   return f"qs:{self.slug}:f={suffix}"
   ```
   Otherwise return the existing `f"qs:{self.slug}"`.

5. **`describe()` method**: Append permanent filter info if set:
   ```python
   if self._permanent_filter:
       desc += f" [permanent filter: {self._permanent_filter}]"
   ```

## Acceptance Criteria

- [ ] `QuerySlugSource(slug="x", permanent_filter={"k": "v"})` stores the filter.
- [ ] `fetch()` merges permanent filter; permanent keys override runtime keys.
- [ ] `prefetch_schema()` uses the permanent filter in its QS call.
- [ ] `cache_key` differs between filtered and unfiltered sources.
- [ ] `describe()` includes filter info when set.
- [ ] Omitting `permanent_filter` preserves existing behavior (no regression).

## Tests

- `test_qs_permanent_filter_merge` — filter merged into fetch conditions.
- `test_qs_permanent_filter_precedence` — permanent key overrides runtime key.
- `test_qs_permanent_filter_cache_key` — filtered source has different cache_key.
- `test_qs_permanent_filter_describe` — describe() includes filter info.
- `test_qs_no_permanent_filter_compat` — omitting permanent_filter works as before.
