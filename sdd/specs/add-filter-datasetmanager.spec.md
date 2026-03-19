# Feature Specification: Permanent Filters for DataSource Sources

**Feature ID**: FEAT-051
**Date**: 2026-03-17
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x

---

## 1. Motivation & Business Requirements

### Problem Statement

Currently, `QuerySlugSource` and `TableSource` only accept filtering at **fetch time**:

- **QuerySlugSource**: conditions are passed as `**params` to `fetch()`, which forwards them to `QS(slug=..., conditions=params)`. There is no way to set conditions that are always applied on every fetch.
- **TableSource**: filtering happens only through the `sql` argument passed to `fetch()`. There is no mechanism to enforce a permanent WHERE clause.

This means that if a caller always needs the same filter (e.g. `{"tenant": "pokemon"}` for a multi-tenant table), they must pass it on **every single fetch/materialize call**. This is error-prone (forget once and you get unfiltered data) and creates boilerplate when the same source is re-used across multiple agent conversations.

A **permanent filter** — set once at source creation — would be merged into every `fetch()` call automatically, regardless of what additional conditions the caller passes at fetch time.

### Goals

- Add an optional `permanent_filter: Optional[Dict[str, Any]]` parameter to `QuerySlugSource.__init__()`.
- Add an optional `permanent_filter: Optional[Dict[str, Any]]` parameter to `TableSource.__init__()`.
- At `fetch()` time, merge the permanent filter with any call-time params/conditions, with the permanent filter taking precedence (it cannot be overridden).
- Expose the `permanent_filter` parameter through `DatasetManager.add_query()`, `DatasetManager.add_table_source()`, and `DatasetManager.add_dataset()` (for `query_slug` and `table` modes).
- For `TableSource`, the permanent filter generates a WHERE clause that is appended to the SQL before execution.
- Update `describe()` on both sources to mention active permanent filters.
- Update `cache_key` to incorporate the permanent filter so that filtered and unfiltered views cache independently.

### Non-Goals (explicitly out of scope)

- Permanent filters for `SQLQuerySource` (the user controls the SQL template directly — they can embed their own WHERE).
- Permanent filters for `InMemorySource` (data is already a DataFrame — use FEAT-050's `filter` param on `add_dataset`).
- Complex filter operators (greater-than, LIKE, regex) — only equality and IN-list matching.
- Filter pushdown optimization for `QuerySlugSource` (QS already receives conditions as a dict; this is inherently pushed down).
- Permanent filters for `MultiQuerySlugSource` (can be added later if needed).

---

## 2. Architectural Design

### Overview

The `permanent_filter` is stored on the source instance at creation time. At `fetch()`, it is merged with runtime params before execution. The merge strategy is: **permanent filter wins** — if the same key appears in both permanent and runtime conditions, the permanent value is used (enforcing the "always filtered" guarantee).

```
Creation:  QuerySlugSource(slug="sales", permanent_filter={"tenant": "pokemon"})
                                                      │
                                                      ▼
Fetch:     source.fetch(region="EMEA")     →  conditions = {"tenant": "pokemon", "region": "EMEA"}
Fetch:     source.fetch(tenant="override") →  conditions = {"tenant": "pokemon"}  (permanent wins)
```

### QuerySlugSource Changes

```python
class QuerySlugSource(DataSource):
    def __init__(
        self,
        slug: str,
        prefetch_schema_enabled: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,  # NEW
    ) -> None:
        self.slug = slug
        self.prefetch_schema_enabled = prefetch_schema_enabled
        self._permanent_filter = permanent_filter or {}

    async def fetch(self, **params) -> pd.DataFrame:
        force_refresh = params.pop('force_refresh', False)
        if force_refresh:
            params['refresh'] = True
        # Merge: permanent filter overwrites runtime params
        merged = {**params, **self._permanent_filter}
        qy = qs_cls(slug=self.slug, conditions=merged)
        ...
```

### TableSource Changes

For `TableSource`, the permanent filter translates to a WHERE clause appended to any SQL passed to `fetch()`. Since `TableSource.fetch()` receives a full SQL string (not a conditions dict), the filter is injected as SQL conditions.

```python
class TableSource(DataSource):
    def __init__(
        self,
        table: str,
        driver: str,
        dsn: Optional[str] = None,
        credentials: Optional[Dict] = None,
        strict_schema: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,  # NEW
    ) -> None:
        ...
        self._permanent_filter = permanent_filter or {}

    def _build_filter_clause(self) -> str:
        """Build a SQL WHERE fragment from permanent_filter.

        Returns empty string if no permanent filter is set.
        Values are safely escaped. List/tuple values use IN (...).
        """
        ...

    async def fetch(self, sql: Optional[str] = None, **params) -> pd.DataFrame:
        # After existing SQL validation...
        # Append permanent filter as WHERE/AND conditions
        if self._permanent_filter:
            sql = self._inject_permanent_filter(sql)
        return await self._run_query(sql)
```

### DatasetManager Integration

| Method | New Parameter | Passed To |
|--------|--------------|-----------|
| `add_query()` | `permanent_filter: Optional[Dict[str, Any]] = None` | `QuerySlugSource(permanent_filter=...)` |
| `add_table_source()` | `permanent_filter: Optional[Dict[str, Any]] = None` | `TableSource(permanent_filter=...)` |
| `add_dataset()` (query_slug mode) | `permanent_filter: Optional[Dict[str, Any]] = None` | `QuerySlugSource(permanent_filter=...)` |
| `add_dataset()` (table mode) | `permanent_filter: Optional[Dict[str, Any]] = None` | `TableSource(permanent_filter=...)` |

### Cache Key Impact

Permanent filters change the data identity, so `cache_key` must include them:

```python
# QuerySlugSource
@property
def cache_key(self) -> str:
    base = f"qs:{self.slug}"
    if self._permanent_filter:
        suffix = hashlib.md5(
            json.dumps(self._permanent_filter, sort_keys=True).encode()
        ).hexdigest()[:8]
        return f"{base}:f={suffix}"
    return base

# TableSource — analogous pattern
```

### Describe Update

Both `describe()` methods should append the permanent filter info:

```python
def describe(self) -> str:
    desc = f"QuerySource slug '{self.slug}'"
    if self._permanent_filter:
        desc += f" [permanent filter: {self._permanent_filter}]"
    return desc
```

### Affected Components

| Component | File | Change |
|-----------|------|--------|
| `DataSource` (ABC) | `sources/base.py` | No change — permanent_filter is source-specific |
| `QuerySlugSource` | `sources/query_slug.py` | Add `permanent_filter` init, merge in `fetch()`, update `cache_key`/`describe()` |
| `TableSource` | `sources/table.py` | Add `permanent_filter` init, inject WHERE in `fetch()`, update `cache_key`/`describe()` |
| `DatasetManager.add_query()` | `tool.py` | Pass through `permanent_filter` |
| `DatasetManager.add_table_source()` | `tool.py` | Pass through `permanent_filter` |
| `DatasetManager.add_dataset()` | `tool.py` | Pass through `permanent_filter` for query_slug/table modes |

---

## 3. Implementation Plan

### Phase 1: QuerySlugSource Permanent Filter

1. Add `permanent_filter` parameter to `QuerySlugSource.__init__()`.
2. Merge permanent filter into conditions in `fetch()` (permanent wins).
3. Include permanent filter in `prefetch_schema()` conditions (so schema reflects filtered data).
4. Update `cache_key` to incorporate the filter hash.
5. Update `describe()` to mention the filter.
6. Unit tests for merge logic, precedence, and cache key uniqueness.

### Phase 2: TableSource Permanent Filter

1. Add `permanent_filter` parameter to `TableSource.__init__()`.
2. Implement `_build_filter_clause()` with safe value escaping (reuse `_escape_value` pattern from `SQLQuerySource`).
3. Inject the WHERE clause into SQL in `fetch()` — handle both cases: SQL with existing WHERE and SQL without.
4. Update `cache_key` and `describe()`.
5. Unit tests for SQL injection safety, WHERE clause generation, and merge with existing WHERE.

### Phase 3: DatasetManager Integration

1. Add `permanent_filter` parameter to `add_query()`, `add_table_source()`, and `add_dataset()`.
2. Pass through to the respective source constructors.
3. Integration tests.

---

## 4. Acceptance Criteria

- [ ] `QuerySlugSource(slug="sales", permanent_filter={"tenant": "pokemon"})` always includes `tenant=pokemon` in QS conditions.
- [ ] Runtime params in `fetch()` are merged with permanent filter; permanent filter keys take precedence.
- [ ] `TableSource(table="public.orders", driver="pg", permanent_filter={"status": "active"})` appends `WHERE status = 'active'` to every SQL in `fetch()`.
- [ ] `TableSource` permanent filter with list values generates `column IN ('a', 'b')` syntax.
- [ ] `TableSource` permanent filter is safely escaped — no SQL injection via filter values.
- [ ] `TableSource` correctly appends `AND` conditions when SQL already contains a WHERE clause.
- [ ] `cache_key` differs between filtered and unfiltered sources with the same slug/table.
- [ ] `describe()` includes the permanent filter in its output for both sources.
- [ ] `add_query(permanent_filter=...)`, `add_table_source(permanent_filter=...)`, and `add_dataset(permanent_filter=...)` correctly propagate to the source.
- [ ] Omitting `permanent_filter` preserves existing behavior — no regression.

---

## 5. Testing Strategy

### Unit Tests

| Test | Description |
|------|-------------|
| `test_qs_permanent_filter_merge` | Permanent filter merged into fetch conditions |
| `test_qs_permanent_filter_precedence` | Permanent key overrides runtime key |
| `test_qs_permanent_filter_cache_key` | Filtered source has different cache_key |
| `test_qs_permanent_filter_describe` | describe() includes filter info |
| `test_qs_no_permanent_filter_compat` | Omitting permanent_filter works as before |
| `test_table_permanent_filter_where` | WHERE clause generated from filter dict |
| `test_table_permanent_filter_and_existing_where` | AND appended to existing WHERE |
| `test_table_permanent_filter_list_values` | IN clause for list values |
| `test_table_permanent_filter_escaping` | Dangerous values are safely escaped |
| `test_table_permanent_filter_cache_key` | Filtered source has different cache_key |
| `test_table_no_permanent_filter_compat` | Omitting permanent_filter works as before |

### Integration Tests

| Test | Description |
|------|-------------|
| `test_add_query_with_permanent_filter` | `add_query(permanent_filter=...)` propagates to source |
| `test_add_table_source_with_permanent_filter` | `add_table_source(permanent_filter=...)` propagates |
| `test_add_dataset_query_slug_permanent_filter` | `add_dataset(query_slug=..., permanent_filter=...)` propagates |
| `test_add_dataset_table_permanent_filter` | `add_dataset(table=..., permanent_filter=...)` propagates |

---

## 6. Dependencies

- **FEAT-030** (DatasetManager Lazy Data Sources): Already implemented — this feature extends `QuerySlugSource` and `TableSource` from that spec.
- **FEAT-050** (add_dataset filter): Independent feature — FEAT-050 filters the DataFrame in-memory after fetch, while FEAT-051 filters at the source level during fetch. They are complementary and can coexist.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SQL injection via permanent_filter values in TableSource | Medium | High | Reuse `SQLQuerySource._escape_value()` pattern; validate column names against `_SAFE_IDENTIFIER_RE` |
| WHERE clause injection breaks complex SQL (subqueries, CTEs) | Low | Medium | Only append to the outermost WHERE; document that complex SQL should embed filters manually |
| QS conditions dict doesn't support the filter key | Low | Medium | QS conditions are free-form dicts — keys map directly to query template params |
| Cache invalidation when permanent_filter changes | Low | Low | Different filter = different cache_key; old entries expire naturally via TTL |

---

## 8. Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree).
- **Reason**: 3 phases, each depends on the previous. Sources must be done before DatasetManager integration.
- **Cross-feature dependencies**: None — FEAT-050 is independent and can be merged separately.
