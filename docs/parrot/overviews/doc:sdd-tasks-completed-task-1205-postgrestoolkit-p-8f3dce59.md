---
type: Wiki Overview
title: 'TASK-1205: PostgresToolkit — migrate introspection queries to `pg_catalog`'
id: doc:sdd-tasks-completed-task-1205-postgrestoolkit-pg-catalog-migration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: which is slower (views over `pg_catalog`), poorer (no system OIDs,
relates_to:
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.postgres
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.sql
  rel: mentions
---

# TASK-1205: PostgresToolkit — migrate introspection queries to `pg_catalog`

**Feature**: FEAT-178 — Database Toolkit Cache Contract & Tool Semantics
**Spec**: `sdd/specs/database-toolkit-cache-contract.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1201
**Assigned-to**: unassigned

---

## Context

`PostgresToolkit` currently introspects via `information_schema`
which is slower (views over `pg_catalog`), poorer (no system OIDs,
no `relfilenode`, partition info hidden) and occasionally
inconsistent with reality. The spec migrates every `_get_*` query
hook to `pg_catalog` directly.

Implements **Module 5** of the spec.

---

## Scope

Rewrite the following query hooks in
`packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py`
against `pg_catalog` (keep the method names so subclass overrides
still work):

- `_get_information_schema_query` — uses `pg_class` + `pg_namespace`.
  Replace the hardcoded `LIMIT 20` (postgres.py:154) with the
  caller-provided `limit`.
- `_get_columns_query` — uses `pg_attribute` + `pg_type` +
  `pg_attrdef` for defaults; uses `col_description()` for comments.
  Filter `attnum > 0 AND NOT attisdropped` to match
  `information_schema.columns` visibility.
- `_get_primary_keys_query` — uses `pg_constraint` `contype = 'p'`.
- `_get_unique_constraints_query` — uses `pg_constraint`
  `contype = 'u'`.

Add two **new** query hooks:

- `_get_indexes_query(schema, table) -> tuple[str, tuple]` — uses
  `pg_index` + `pg_class`. One row per index: index name, column
  list, uniqueness flag.
- `_get_foreign_keys_query(schema, table) -> tuple[str, tuple]` —
  uses `pg_constraint` `contype = 'f'`. Returns referencing
  columns, referenced schema/table/columns, ON UPDATE / ON DELETE
  actions.

In `_introspect_table_full` (added by TASK-1203), flip the
`source` value from `"information_schema"` to `"pg_catalog"`
once these queries are live. Same in `_build_table_metadata`
(sql.py:811) when the result comes back from a PG-flavoured
toolkit.

Unit tests per §4:
- `test_pg_catalog_columns_query`
- `test_pg_catalog_indexes_query`
- `test_pg_catalog_foreign_keys_query`
- `test_pg_catalog_full_introspection_matches_information_schema`

**NOT in scope**: behaviour changes outside `PostgresToolkit`,
non-PG toolkits (BigQuery, Elastic, Influx, DocumentDB).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py` | MODIFY | Rewrite four queries, add two new ones |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | Flip `source` to `"pg_catalog"` when running under a PG-derived toolkit (or read from a new `self._metadata_source` class attribute) |
| `packages/ai-parrot/tests/bots/database/test_postgres_introspection.py` | CREATE | Tests using the existing test PG fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
from parrot.bots.database.models import TableMetadata
from parrot.bots.database.toolkits.sql import SQLToolkit
```

### Existing Signatures to Use
```python
# postgres.py
class PostgresToolkit(SQLToolkit):
    def _get_information_schema_query(
        self, schema: Optional[str] = None,
    ) -> tuple[str, tuple]: ...           # line 121, LIMIT 20 hardcoded at line 154
    def _get_columns_query(self, schema, table) -> tuple[str, tuple]: ...  # line 156

# sql.py — base hooks (PG inherits via SQLToolkit)
class SQLToolkit:
    def _get_primary_keys_query(self, schema, table) -> tuple[str, tuple]: ...  # line 584
    def _get_unique_constraints_query(self, schema, table) -> tuple[str, tuple]: ...  # line 607
    async def _build_table_metadata(
        self, schema, table, table_type, comment=None,
    ) -> Optional[TableMetadata]: ...     # line 811
```

### Does NOT Exist
- ~~`PostgresToolkit._get_indexes_query`~~ — introduced here.
- ~~`PostgresToolkit._get_foreign_keys_query`~~ — introduced here.

---

## Implementation Notes

### Schema-qualify everything (spec §7)
Reference every catalog table with the `pg_catalog.` prefix
(`pg_catalog.pg_class`, `pg_catalog.pg_namespace`, etc.) to avoid
`search_path` surprises in customer DBs that have non-standard
search paths.

### Visibility filter for columns
`pg_attribute` includes dropped columns and system columns. Match
the `information_schema.columns` visibility:
```sql
WHERE a.attnum > 0 AND NOT a.attisdropped
```

### Parameter binding
Use parameter binding for `schema` and `table` (asyncpg `$1`,
`$2` style — match the existing code's convention in the file).
Do not interpolate even when the values come from
`self.allowed_schemas` — keeps the surface uniform.

### Reference shape for the new indexes query
```sql
SELECT
    i.relname AS index_name,
    ix.indisunique AS is_unique,
    ix.indisprimary AS is_primary,
    ARRAY(
        SELECT pg_get_indexdef(ix.indexrelid, k + 1, true)
        FROM generate_subscripts(ix.indkey, 1) AS k
    ) AS column_expressions
FROM pg_catalog.pg_index ix
JOIN pg_catalog.pg_class i ON i.oid = ix.indexrelid
JOIN pg_catalog.pg_class t ON t.oid = ix.indrelid
JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = $1 AND t.relname = $2
ORDER BY i.relname;
```

### Reference shape for the new foreign-keys query
```sql
SELECT
    c.conname AS constraint_name,
    ARRAY(
        SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY x(attnum, ord)
        JOIN pg_catalog.pg_attribute a
          ON a.attrelid = c.conrelid AND a.attnum = x.attnum
        ORDER BY x.ord
    ) AS referencing_columns,
    rn.nspname AS referenced_schema,
    rt.relname AS referenced_table,
    ARRAY(
        SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY x(attnum, ord)
        JOIN pg_catalog.pg_attribute a
          ON a.attrelid = c.confrelid AND a.attnum = x.attnum
        ORDER BY x.ord
    ) AS referenced_columns,
    c.confupdtype AS on_update,
    c.confdeltype AS on_delete
FROM pg_catalog.pg_constraint c
JOIN pg_catalog.pg_class t  ON t.oid = c.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
JOIN pg_catalog.pg_class rt ON rt.oid = c.confrelid
JOIN pg_catalog.pg_namespace rn ON rn.oid = rt.relnamespace
WHERE c.contype = 'f' AND n.nspname = $1 AND t.relname = $2;
```

### Setting `source`
Two options — pick one and use it everywhere:
1. **Class attribute on toolkit**:
   `class PostgresToolkit: _metadata_source = "pg_catalog"`
   then `_build_table_metadata` reads
   `meta.source = self._metadata_source`.
2. **Direct in `_introspect_table_full` for PG toolkits**: in
   `_introspect_table_full` (TASK-1203), `meta.source = "pg_catalog"`
   when `isinstance(self, PostgresToolkit)`.

Option 1 is cleaner and matches the inheritance model better.
The base `SQLToolkit._metadata_source` defaults to
`"information_schema"`.

### Backwards-compat for `_get_information_schema_query` name
The method name stays for API stability — subclasses outside
`PostgresToolkit` (e.g., `BigQueryToolkit`) override it and must
keep working. Only the body changes for PG.

---

## Acceptance Criteria

- [ ] All four existing `_get_*` queries in `PostgresToolkit` are
      rewritten against `pg_catalog`
- [ ] `LIMIT` is honored from the caller, not hardcoded to 20
- [ ] `_get_indexes_query` exists and returns one row per index
- [ ] `_get_foreign_keys_query` exists and returns referencing /
      referenced columns plus action codes
- [ ] Visibility filter `attnum > 0 AND NOT attisdropped` is
      applied in the columns query
- [ ] Every catalog reference is `pg_catalog.`-qualified
- [ ] Schema / table names are parameter-bound, not interpolated
- [ ] `meta.source == "pg_catalog"` for entries produced by
      `PostgresToolkit._build_table_metadata` /
      `_introspect_table_full`
- [ ] `test_pg_catalog_full_introspection_matches_information_schema`
      passes against the test PG fixture
- [ ] Existing `PostgresToolkit` tests still pass

---

## Test Specification

```python
import pytest
from parrot.bots.database.toolkits.postgres import PostgresToolkit


@pytest.mark.integration
async def test_columns_query_matches_information_schema(seeded_pg, pg_toolkit):
    """For pokemon.stores, the new pg_catalog query returns at least
    the same name/type/nullable/default tuples as the old IS query."""
    new = await pg_toolkit._fetch_columns("pokemon", "stores")  # uses new hook
    # Cross-check against information_schema
    async with pg_toolkit._pool.acquire() as conn:
        old = await conn.fetch(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema=$1 AND table_name=$2 "
            "ORDER BY ordinal_position",
            "pokemon", "stores",
        )
    assert {c["name"] for c in new} == {r["column_name"] for r in old}


@pytest.mark.integration
async def test_indexes_query_returns_unique_flag(seeded_pg, pg_toolkit):
    out = await pg_toolkit._fetch_indexes("pokemon", "stores")
    pk_idx = [i for i in out if i["is_primary"]]
    assert len(pk_idx) == 1


@pytest.mark.integration
async def test_foreign_keys_query_shape(seeded_pg_with_fks, pg_toolkit):
    out = await pg_toolkit._fetch_foreign_keys("networkninja", "forms")
    assert any(fk["referenced_table"] == "organizations" for fk in out)


@pytest.mark.integration
async def test_full_introspection_source_is_pg_catalog(seeded_pg, pg_toolkit):
    meta = await pg_toolkit._build_table_metadata(
        "pokemon", "stores", table_type="BASE TABLE",
    )
    assert meta.source == "pg_catalog"
```

---

## Agent Instructions

1. Confirm TASK-1201 is in `sdd/tasks/completed/` (this task does
   not depend on the cache or sql.py changes — runs in parallel
   with TASK-1202/1203/1204).
2. Re-verify line numbers in `postgres.py`.
3. Test each query manually with `psql` against the test DB
   before wiring it in — catch typos early.
4. Implement.
5. Run integration tests against the seeded PG fixture.
6. Move task file to `completed/` and update the per-spec index.
7. Fill in the Completion Note.

---

## Completion Note

Implemented on branch `feat-178-database-toolkit-cache-contract`.

- Added `_metadata_source = "pg_catalog"` class attribute on `PostgresToolkit`; base `SQLToolkit` defaults to `"information_schema"`.
- Rewrote `_get_information_schema_query`: uses `pg_catalog.pg_class` + `pg_catalog.pg_namespace`; honors caller-provided `limit` as `$3` (no more hardcoded 20); returns `obj_description()` for comments.
- Rewrote `_get_columns_query`: uses `pg_catalog.pg_attribute` + `pg_catalog.pg_type` + `pg_catalog.pg_attrdef`; filters `attnum > 0 AND NOT attisdropped`; `col_description()` for column comments.
- Added `_get_primary_keys_query` override: uses `pg_catalog.pg_constraint` `contype='p'`; replaces `information_schema` base.
- Added `_get_unique_constraints_query` override: uses `pg_catalog.pg_constraint` `contype='u'`; compatible shape with base-class grouping logic.
- Added `_get_indexes_query`: returns one row per index with `index_name`, `is_unique`, `is_primary`, `column_expressions` via `pg_get_indexdef`.
- Added `_get_foreign_keys_query`: returns FK constraints with referencing/referenced columns and ON UPDATE/DELETE action codes.
- Updated base `SQLToolkit._build_table_metadata` to stamp `source=self._metadata_source` on returned `TableMetadata`.
- Updated `_introspect_table_full` to use `self._metadata_source` instead of hardcoded `"information_schema"`.
- Base `_get_information_schema_query` updated to accept and forward `limit` parameter; `_search_in_database` passes the caller-supplied limit.
- 38/38 unit tests pass; 119/119 database tests pass; ruff clean.
