# Feature Specification: DatasetManager TableSource Column List

**Feature ID**: FEAT-061
**Date**: 2026-03-24
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.9.x

---

## 1. Motivation & Business Requirements

### Problem Statement

When a `TableSource` is registered with `DatasetManager`, **all columns** from the database table are exposed to the LLM — both in the schema guide and in fetch results. There is no mechanism to restrict which columns are visible or queryable.

This creates two problems:

1. **Security**: Sensitive columns (e.g. `ssn`, `salary`, `password_hash`, `email`) are exposed to the LLM even when they are not relevant to the task. The LLM can construct `SELECT *` or explicitly reference any column.
2. **Noise**: Tables with many columns produce verbose schema guides. Restricting to only relevant columns reduces token usage and improves LLM query quality.

Currently, the only filtering mechanisms are row-level: `permanent_filter` (FEAT-051) restricts rows via WHERE clauses, and `filter` (FEAT-050) filters DataFrame rows post-fetch. **No column-level restriction exists.**

### Goals

- Allow `TableSource` to accept an optional `allowed_columns` list at construction time.
- When `allowed_columns` is set, **only those columns** appear in schema prefetch results, LLM guides, `describe()`, and `get_metadata()`.
- Validate LLM-generated SQL at `fetch()` time: reject queries that reference columns not in `allowed_columns`.
- Filter fetched DataFrame columns to only include `allowed_columns` (defense-in-depth).
- Instruct the LLM (via describe/guide text) that it **must not** reference columns outside the allowed list.
- Incorporate `allowed_columns` into the `cache_key` so differently-scoped views of the same table cache independently.

### Non-Goals (explicitly out of scope)

- Row-level security (already handled by `permanent_filter` / FEAT-051).
- Column-level restrictions for non-TableSource sources (DataFrameSource, QuerySlugSource, etc.).
- Per-user or per-session dynamic column filtering (this is a static, per-registration restriction).
- Full SQL parsing — column validation uses regex heuristics consistent with existing `fetch()` validation.

---

## 2. Architectural Design

### Overview

Add an optional `allowed_columns: Optional[List[str]]` parameter to `TableSource.__init__()`. When set:

1. **Schema prefetch** filters `_schema` to only include allowed columns.
2. **`describe()`** mentions the column restriction and lists allowed columns.
3. **`fetch(sql)`** validates that the SQL SELECT clause only references allowed columns; rejects `SELECT *` with a clear error message.
4. **Post-fetch filtering** drops any columns not in `allowed_columns` from the returned DataFrame.
5. **`cache_key`** includes a hash of `allowed_columns` for independent caching.

The LLM sees only the allowed columns in all interfaces (guide, metadata, describe) and receives explicit instructions not to use any other columns.

### Component Diagram

```
Registration (add_table_source)
  │
  ├─ allowed_columns param ──→ TableSource.__init__()
  │                                 │
  │                      prefetch_schema() ──→ filter _schema to allowed_columns
  │                                 │
  │                      describe() ──→ "[restricted to N columns: col1, col2, ...]"
  │                                 │
  │                      fetch(sql) ──→ _validate_column_access(sql)
  │                                 │        │
  │                                 │   reject SELECT * / disallowed columns
  │                                 │        │
  │                                 │   _run_query(sql)
  │                                 │        │
  │                                 └── filter DataFrame columns ──→ return
  │
  └─ DatasetEntry.columns ──→ returns only allowed columns (via filtered _schema)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TableSource` | modifies | New `allowed_columns` param, schema filtering, SQL validation |
| `DatasetManager.add_table_source()` | modifies | Pass `allowed_columns` through to TableSource |
| `DatasetEntry.columns` | no change | Already reads from `source._schema` — automatically filtered |
| `DatasetInfo` | no change | Populated from `DatasetEntry.columns` — automatically filtered |
| `_generate_dataframe_guide()` | no change | Uses `DatasetEntry.columns` — automatically filtered |

### Data Models

```python
# TableSource constructor gains one new parameter:
class TableSource(DataSource):
    def __init__(
        self,
        table: str,
        driver: str,
        dsn: Optional[str] = None,
        credentials: Optional[Dict] = None,
        strict_schema: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,
        allowed_columns: Optional[List[str]] = None,  # NEW
    ) -> None:
        ...
        self._allowed_columns: Optional[List[str]] = allowed_columns
```

### New Public Interfaces

```python
# DatasetManager.add_table_source() gains allowed_columns parameter:
async def add_table_source(
    self,
    name: str,
    table: str,
    driver: str,
    description: Optional[str] = None,
    dsn: Optional[str] = None,
    credentials: Optional[Dict] = None,
    permanent_filter: Optional[Dict[str, Any]] = None,
    strict_schema: bool = True,
    allowed_columns: Optional[List[str]] = None,  # NEW
    is_active: bool = True,
    metadata: Optional[Dict] = None,
) -> str:
    ...

# TableSource.allowed_columns property (read-only):
@property
def allowed_columns(self) -> Optional[List[str]]:
    """Return the allowed columns list, or None if unrestricted."""
    return self._allowed_columns
```

---

## 3. Module Breakdown

### Module 1: TableSource — allowed_columns parameter and schema filtering

- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py`
- **Responsibility**:
  - Accept `allowed_columns` in `__init__()`, validate each name against `_SAFE_IDENTIFIER_RE`.
  - After `prefetch_schema()` completes, filter `_schema` to only include keys in `allowed_columns`. Warn (or raise if `strict_schema`) if any allowed column is not found in the actual schema.
  - Update `describe()` to mention column restrictions and list allowed columns.
  - Update `cache_key` to incorporate `allowed_columns` hash.
- **Depends on**: nothing new

### Module 2: TableSource — SQL column validation in fetch()

- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py`
- **Responsibility**:
  - In `fetch()`, when `allowed_columns` is set:
    - Reject `SELECT *` with a clear error: "SELECT * is not allowed. Use SELECT {allowed_columns} instead."
    - Use regex to extract column references from the SELECT clause and validate against `allowed_columns`.
    - After `_run_query()`, filter the returned DataFrame to only include `allowed_columns` (defense-in-depth).
  - The LLM error messages must be actionable: tell the LLM exactly which columns it CAN use.
- **Depends on**: Module 1

### Module 3: DatasetManager — pass allowed_columns through

- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**:
  - Add `allowed_columns` parameter to `add_table_source()`.
  - Pass it through to `TableSource(...)` constructor.
  - Include column restriction info in the registration log message.
- **Depends on**: Module 1

### Module 4: Unit tests

- **Path**: `packages/ai-parrot/tests/tools/test_tablesource_allowed_columns.py`
- **Responsibility**: Full test coverage for the new feature.
- **Depends on**: Modules 1, 2, 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_allowed_columns_stored` | 1 | Validates `allowed_columns` is stored and accessible via property |
| `test_allowed_columns_validated` | 1 | Invalid column names (e.g. `"col;DROP"`) raise ValueError |
| `test_schema_filtered_to_allowed` | 1 | After prefetch, `_schema` only contains allowed columns |
| `test_schema_missing_allowed_column_strict` | 1 | Raises if allowed column not in actual schema (strict_schema=True) |
| `test_schema_missing_allowed_column_lenient` | 1 | Warns but continues if strict_schema=False |
| `test_describe_mentions_restriction` | 1 | `describe()` output contains "restricted" and lists allowed columns |
| `test_cache_key_includes_allowed_columns` | 1 | Different allowed_columns produce different cache keys |
| `test_cache_key_none_unchanged` | 1 | No allowed_columns → cache_key unchanged from current behavior |
| `test_fetch_rejects_select_star` | 2 | `SELECT * FROM table` raises ValueError with helpful message |
| `test_fetch_rejects_disallowed_column` | 2 | SQL referencing non-allowed column raises ValueError |
| `test_fetch_allows_valid_columns` | 2 | SQL using only allowed columns passes validation |
| `test_fetch_filters_dataframe_columns` | 2 | Returned DataFrame only has allowed columns |
| `test_no_restriction_unchanged_behavior` | 2 | When `allowed_columns=None`, all existing behavior is unchanged |
| `test_add_table_source_passes_allowed_columns` | 3 | `add_table_source(allowed_columns=[...])` creates TableSource with restriction |

### Integration Tests

| Test | Description |
|---|---|
| `test_guide_shows_only_allowed_columns` | Full registration + guide generation: only allowed columns appear |
| `test_metadata_shows_only_allowed_columns` | `get_metadata()` returns only allowed columns in columns list |

### Test Data / Fixtures

```python
@pytest.fixture
def table_source_with_columns():
    """TableSource with allowed_columns restriction."""
    return TableSource(
        table="public.employees",
        driver="pg",
        allowed_columns=["id", "name", "department"],
    )

@pytest.fixture
def mock_full_schema():
    """Full schema that includes restricted columns."""
    return {
        "id": "integer",
        "name": "varchar",
        "department": "varchar",
        "salary": "numeric",
        "ssn": "varchar",
        "password_hash": "varchar",
    }
```

---

## 5. Acceptance Criteria

- [ ] `TableSource` accepts optional `allowed_columns` parameter
- [ ] Schema prefetch filters `_schema` to only allowed columns
- [ ] `describe()` clearly indicates column restriction and lists allowed columns
- [ ] `fetch()` rejects `SELECT *` when `allowed_columns` is set, with actionable error
- [ ] `fetch()` rejects SQL referencing columns not in `allowed_columns`
- [ ] Returned DataFrame is filtered to only `allowed_columns` (defense-in-depth)
- [ ] `cache_key` incorporates `allowed_columns` for independent caching
- [ ] `add_table_source()` accepts and passes through `allowed_columns`
- [ ] LLM guide and metadata show only allowed columns
- [ ] All unit tests pass
- [ ] No breaking changes — `allowed_columns=None` preserves existing behavior exactly

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Follow the `permanent_filter` pattern from FEAT-051 for parameter threading (constructor → validation → cache_key).
- Validate column names using existing `_validate_identifier()` / `_SAFE_IDENTIFIER_RE`.
- Column validation in `fetch()` uses regex heuristics (not a full SQL parser), consistent with existing table-name validation.
- Error messages from `fetch()` must be LLM-friendly: include the list of allowed columns so the LLM can self-correct.

### SQL Column Extraction Strategy

For `SELECT *` detection: simple regex `r'\bSELECT\s+\*\s'` (case-insensitive).

For column extraction from SELECT clause: extract text between `SELECT` and `FROM`, split on commas, strip aliases (`AS ...`), and check each identifier against `allowed_columns`. This is a heuristic — it handles common LLM-generated SQL patterns but not all SQL edge cases (subqueries, expressions). The defense-in-depth DataFrame filter catches anything the regex misses.

### Known Risks / Gotchas

- **SQL expressions**: LLM may write `SELECT UPPER(salary)` which contains a disallowed column inside a function call. The regex heuristic may not catch all cases. The post-fetch DataFrame column filter is the safety net.
- **Aggregate queries**: `SELECT COUNT(*)` should NOT be rejected — it doesn't reference specific columns. The `SELECT *` rejection must distinguish `COUNT(*)` from `SELECT *`.
- **Column aliases in results**: If the LLM uses `SELECT name AS employee_name`, the DataFrame column will be `employee_name`, not `name`. The post-fetch filter should handle this gracefully (filter by intersection, not strict match).

### External Dependencies

None — uses only existing dependencies.

---

## 7. Open Questions

- [ ] Should `allowed_columns` validation against actual schema happen during `prefetch_schema()` or at `add_table_source()` registration time? (Recommendation: during `prefetch_schema()`, since that's when we first learn the actual columns.): during prefech_schema.
- [ ] Should the feature support column aliasing (e.g. `allowed_columns={"id": "employee_id"}` mapping)? (Recommendation: out of scope for v1, can be added later.): out of scope for v1, can be added later.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules 1–3 modify the same two files (`table.py` and `tool.py`), so sequential execution avoids merge conflicts.
- **Cross-feature dependencies**: FEAT-051 (permanent_filter) must be merged first — this feature follows the same pattern. FEAT-059 (description) should be merged for a clean base, but is not strictly required.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-24 | Jesus Lara | Initial draft |
