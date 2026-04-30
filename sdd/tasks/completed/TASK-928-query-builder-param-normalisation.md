# TASK-928: Query-Builder Parameter Normalisation — `:name` → `$N`

**Feature**: FEAT-118 — Database Toolkit asyncpg Native Boundary Refactor
**Spec**: `sdd/specs/database-toolkit-asyncpg-boundary-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-926, TASK-927
**Assigned-to**: unassigned

---

## Context

Implements Module 3 of the spec. Fixes defects D2 and D3. Currently:

- All `_get_*_query` builders emit SQLAlchemy-style `:name` placeholders and
  return `(sql, dict)`.
- `_execute_asyncdb` ignores the params entirely — calls `conn.query(sql)`
  with bare SQL containing unsubstituted placeholders.
- This causes metadata warm-up to silently return 0 rows (`0/N warmed`).

After this task:
- All builders return `(sql, tuple)` with `$1, $2, ...` asyncpg placeholders.
- `_execute_asyncdb` accepts a positional tuple and forwards via
  `raw.fetch(sql, *params)`.
- All call sites (`_search_in_database`, `_build_table_metadata`) pass params
  through.

This includes BigQuery builders — asyncdb's BigQuery driver uses `@param`
style or positional depending on the query API. Verify the asyncdb bigquery
driver's convention and adapt accordingly.

---

## Scope

- Convert `SQLToolkit._get_information_schema_query` to emit `$1, $2, $3`
  and return `(sql, tuple)`.
- Convert `SQLToolkit._get_columns_query` to emit `$1, $2` and return
  `(sql, tuple)`.
- Convert `SQLToolkit._get_primary_keys_query` — same.
- Convert `SQLToolkit._get_unique_constraints_query` — same.
- Convert `PostgresToolkit._get_information_schema_query` override — same.
- Convert `PostgresToolkit._get_columns_query` override — same.
- Convert `BigQueryToolkit._get_information_schema_query` override — adapt
  to asyncdb bigquery driver's parameter convention.
- Convert `BigQueryToolkit._get_columns_query` override — same.
- Modify `_execute_asyncdb` to accept `params: tuple = ()` and call
  `raw.fetch(sql, *params)` instead of `conn.query(sql)`.
- Update `_search_in_database` to pass params to `_execute_asyncdb`.
- Update `_build_table_metadata` to pass params to `_execute_asyncdb`.
- Write unit tests for placeholder emission and param forwarding.

**NOT in scope**: connection boundary (TASK-926), SQLAlchemy deletion
(TASK-927), transaction rewrite (TASK-929), NavigatorToolkit cleanup
(TASK-930).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | `_get_*_query` builders, `_execute_asyncdb`, `_search_in_database`, `_build_table_metadata` |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py` | MODIFY | `_get_information_schema_query`, `_get_columns_query` overrides |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/bigquery.py` | MODIFY | `_get_information_schema_query`, `_get_columns_query` overrides |
| `tests/unit/bots/database/toolkits/test_warm_cache_params.py` | CREATE | Unit tests for param normalisation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures to Modify

```python
# sql.py:382-411 — _get_information_schema_query (base)
def _get_information_schema_query(
    self,
    search_term: str,
    schemas: List[str],
) -> tuple[str, Dict[str, Any]]:
    # Currently: `:schemas`, `:term`, `:limit` placeholders, returns dict
    # CHANGE TO: `$1`, `$2`, `$3` placeholders, return tuple

# sql.py:413-422 — _get_columns_query (base)
def _get_columns_query(self, schema: str, table: str) -> tuple[str, Dict[str, Any]]:
    # Currently: `:schema`, `:table` placeholders, returns dict
    # CHANGE TO: `$1`, `$2`, return tuple

# sql.py:424-437 — _get_primary_keys_query (base)
def _get_primary_keys_query(self, schema: str, table: str) -> tuple[str, Dict[str, Any]]:
    # Currently: `:schema`, `:table`, returns dict
    # CHANGE TO: `$1`, `$2`, return tuple

# sql.py:439-473 — _get_unique_constraints_query (base)
def _get_unique_constraints_query(self, schema: str, table: str) -> tuple[str, Dict[str, Any]]:
    # Currently: `:schema`, `:table`, returns dict
    # CHANGE TO: `$1`, `$2`, return tuple

# sql.py:487-508 — _execute_asyncdb
async def _execute_asyncdb(
    self,
    sql: str,
    limit: int = 1000,
    timeout: int = 30,
) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    # Currently calls: conn.query(sql)
    # CHANGE TO: accept params, call raw.fetch(sql, *params)

# sql.py:546-551 — _search_in_database (params dropped)
info_sql, params = self._get_information_schema_query(search_term, target_schemas)
data, error = await self._execute_asyncdb(info_sql, limit=limit, timeout=30)
# CHANGE TO: pass params through

# sql.py:591-625 — _build_table_metadata (params dropped)
col_sql, col_params = self._get_columns_query(schema, table)
col_data, _ = await self._execute_asyncdb(col_sql, limit=0, timeout=15)
# CHANGE TO: pass col_params through (same for pk_params, uq_params)

# postgres.py:97-126 — _get_information_schema_query (PG override)
# Currently: `:schemas`, `:term`, `:limit`, returns dict
# CHANGE TO: `$1`, `$2`, `$3`, return tuple

# postgres.py:128-148 — _get_columns_query (PG override)
# Currently: `:schema`, `:table`, returns dict
# CHANGE TO: `$1`, `$2`, return tuple

# bigquery.py:56-78 — _get_information_schema_query (BQ override)
# Currently: `:term`, `:limit`, returns dict
# Adapt to asyncdb bigquery driver convention

# bigquery.py:80-96 — _get_columns_query (BQ override)
# Currently: `:table`, returns dict
# Adapt to asyncdb bigquery driver convention
```

### Return Type Change
```python
# BEFORE (all builders):
def _get_columns_query(self, schema, table) -> tuple[str, Dict[str, Any]]:
    return sql, {"schema": schema, "table": table}

# AFTER (all builders):
def _get_columns_query(self, schema, table) -> tuple[str, tuple]:
    return sql, (schema, table)
```

### _execute_asyncdb Signature Change
```python
# BEFORE:
async def _execute_asyncdb(self, sql, limit=1000, timeout=30):
    async with self._acquire_asyncdb_connection() as conn:
        result, error = await conn.query(sql)

# AFTER:
async def _execute_asyncdb(self, sql, params=(), limit=1000, timeout=30):
    async with self._acquire_asyncdb_connection() as conn:
        # conn is now raw asyncpg.Connection (after TASK-926)
        if params:
            rows = await conn.fetch(sql, *params)
        else:
            rows = await conn.fetch(sql)
        return [dict(r) for r in rows] if rows else [], None
```

### Does NOT Exist
- ~~Translating `:name` → `$N` at execute time~~ — normalise at builder time
- ~~`conn.query(sql, params=dict)` with named params~~ — asyncpg uses positional only
- ~~`asyncpg.Connection.execute(sql, params_dict)` with dict~~ — only positional `*args`
- ~~Keeping `:name` style "for readability"~~ — lead rejects mixed styles

---

## Implementation Notes

### Conversion Pattern
```python
# BEFORE:
sql = """
    SELECT ... WHERE table_schema = :schema AND table_name = :table
"""
return sql, {"schema": schema, "table": table}

# AFTER:
sql = """
    SELECT ... WHERE table_schema = $1 AND table_name = $2
"""
return sql, (schema, table)
```

### asyncpg `ANY($1)` Pattern
For arrays (like `schemas` list):
```python
# asyncpg handles array params natively
sql = "... WHERE table_schema = ANY($1) ..."
params = (schemas,)  # list is passed as-is; asyncpg converts to PG array
```

### BigQuery Consideration
asyncdb's BigQuery driver may use a different parameter style. Check
`asyncdb/drivers/bigquery.py` for the `execute`/`fetch` method signatures.
If BigQuery uses `@param` named style, keep that for BQ-specific builders
but still return a tuple with the params in order.

### Key Constraints
- Every builder's return type changes from `tuple[str, Dict]` to `tuple[str, tuple]`.
- `_execute_asyncdb` is the ONLY execution path after TASK-927 removes SQLAlchemy.
- After TASK-926, `conn` inside `_execute_asyncdb` is raw asyncpg — use `fetch`
  not `query`.

---

## Acceptance Criteria

- [ ] All `_get_*_query` builders return `(sql, tuple)` with `$N` placeholders
- [ ] `_execute_asyncdb` accepts `params: tuple` and forwards via `*params`
- [ ] `_search_in_database` passes params through to `_execute_asyncdb`
- [ ] `_build_table_metadata` passes params through to `_execute_asyncdb`
- [ ] `test_columns_query_emits_dollar_placeholders` passes
- [ ] `test_execute_asyncdb_forwards_tuple_params` passes
- [ ] Warm-up log shows `N/N warmed` (not `0/N`) in integration test
- [ ] BigQuery builders adapted to asyncdb bigquery driver convention

---

## Test Specification

```python
# tests/unit/bots/database/toolkits/test_warm_cache_params.py
import pytest


class TestQueryBuilderPlaceholders:
    def test_columns_query_emits_dollar_placeholders(self):
        """_get_columns_query returns $1, $2 and a tuple."""
        # Instantiate a minimal PostgresToolkit (mock connection)
        sql, params = toolkit._get_columns_query("auth", "programs")
        assert "$1" in sql and "$2" in sql
        assert ":schema" not in sql and ":table" not in sql
        assert params == ("auth", "programs")

    def test_information_schema_query_dollar_placeholders(self):
        sql, params = toolkit._get_information_schema_query("prog", ["auth", "public"])
        assert "$1" in sql
        assert ":schemas" not in sql
        assert isinstance(params, tuple)

    def test_primary_keys_query_dollar_placeholders(self):
        sql, params = toolkit._get_primary_keys_query("auth", "programs")
        assert "$1" in sql and "$2" in sql
        assert isinstance(params, tuple)


class TestExecuteAsyncdbParams:
    @pytest.mark.asyncio
    async def test_execute_asyncdb_forwards_tuple_params(self):
        """_execute_asyncdb passes params to raw conn.fetch."""
        # Mock raw conn, verify fetch called with (sql, *params)
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-926 and TASK-927 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm all `_get_*_query` signatures
4. **Check asyncdb BigQuery driver** — `grep` for param style in asyncdb bigquery driver
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** systematically: builders first, then `_execute_asyncdb`, then call sites
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-928-query-builder-param-normalisation.md`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-29
**Notes**: All `_get_*_query` builders normalised to `$N` positional placeholders
returning `(sql, tuple)`. SQLToolkit base: $1/$2/$3 for schemas/term/limit.
PostgresToolkit overrides: $1/$2/$3 with pg_class JOIN for column comments.
BigQueryToolkit: asyncdb BQ driver has no positional param support; values
inlined with SQL-safe escaping (`_validate_identifier` for schema names,
single-quote doubling for search terms), empty tuple `()` returned.
`_execute_asyncdb` updated: `params: tuple = ()` accepted; forwards via
`conn.fetch(sql, *params)`. Call sites (_search_in_database,
_build_table_metadata) pass params through. 14 new tests in
test_warm_cache_params.py; all 78 unit tests pass.

**Deviations from spec**: BigQuery builders use value inlining with SQL escaping
rather than asyncdb-native `@param` style (asyncdb BQ driver wraps
google.cloud.bigquery.Client and its parameter support differs significantly
from asyncpg; inlining is safe given identifier validation + quote doubling).
