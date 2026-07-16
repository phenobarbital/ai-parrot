---
type: Wiki Overview
title: 'TASK-1204: SQLToolkit — fix `search_schema`, add `describe_table`, repurpose
  `generate_query`'
id: doc:sdd-tasks-completed-task-1204-sqltoolkit-methods-fix-extend-repurpose-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The three LLM-visible tools on `SQLToolkit` are the core of the
relates_to:
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.sql
  rel: mentions
---

# TASK-1204: SQLToolkit — fix `search_schema`, add `describe_table`, repurpose `generate_query`

**Feature**: FEAT-178 — Database Toolkit Cache Contract & Tool Semantics
**Spec**: `sdd/specs/database-toolkit-cache-contract.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1202, TASK-1203
**Assigned-to**: unassigned

---

## Context

The three LLM-visible tools on `SQLToolkit` are the core of the
defect this feature fixes: `search_schema` early-returns on
partial cache hits, `generate_query` accepts empty `columns: []`
stubs, and there is no `describe_table` tool to force a
`Completeness.FULL` view of a table.

Implements **Module 4** of the spec.

---

## Scope

- **Fix `search_schema`** (sql.py:106):
  - Drop the early-return at sql.py:125-132.
  - Call `await self.cache_partition.search(target_schemas, search_term, completeness_min=Completeness.NAME_ONLY, limit=limit)` (new API from TASK-1202).
  - Call `await self._search_in_database(search_term, schema_name, limit)`.
  - Deduplicate by `(schema, tablename)`, sort by relevance score
    descending, truncate to `limit`.
  - Update the docstring to state explicitly: searches
    *identifiers (table/column/comment names), not data values*.
- **Add `describe_table`** (new public method, decorated as a tool):
  - Signature: `async def describe_table(self, schema: str, table: str) -> Optional[TableMetadata]`.
  - Try `cache_partition.get(schema, table, required=Completeness.FULL)`.
  - On `None`, call `await self._introspect_table_full(schema, table)`
    (from TASK-1203), then `cache_partition.store_table_metadata(meta)`.
  - Return the metadata (or `None` if the table truly does not
    exist).
- **Repurpose `generate_query`** (sql.py:137):
  - Same signature `(natural_language, target_tables=None, query_type="SELECT")`.
  - If `target_tables` is empty: call
    `await self.search_schema(natural_language, limit=5)` to
    discover candidates; take top 3.
  - For each resolved target (`"schema.table"` or fallback by
    iterating `allowed_schemas`), call `await self.describe_table(schema, table)`.
  - Render a templated `SELECT` skeleton: column list from the
    introspected `meta.columns`, plus a YAML block of the full
    per-table metadata. Skeleton format:
    ```
    -- Auto-generated SELECT skeleton (LLM should refine WHERE/JOIN):
    SELECT <col1>, <col2>, ...
    FROM <schema>.<table>
    -- TODO: WHERE clause for "<natural_language>"
    ```
  - Return the rendered string (skeleton + YAML).
- Update `exclude_tools` (sql.py:70) to hide the new private
  helpers (`_introspect_table_full` etc.) — but **expose**
  `describe_table` so the agent registers `db_describe_table`.
- Tests per §4: `test_search_schema_merges_cache_and_db`,
  `test_search_schema_no_early_return`,
  `test_search_schema_does_not_match_data_values`,
  `test_describe_table_promotes_stub_to_full`,
  `test_describe_table_coalesces_concurrent_calls`,
  `test_generate_query_calls_describe_for_each_target`,
  `test_generate_query_emits_skeleton_with_real_columns`.

**NOT in scope**: `pg_catalog` migration (TASK-1205), prompt
layer wiring (TASK-1206), regression integration tests (TASK-1207).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | Fix `search_schema`, add `describe_table`, repurpose `generate_query`, update `exclude_tools` |
| `packages/ai-parrot/tests/bots/database/test_sql_toolkit_methods.py` | CREATE | Unit tests for the three methods |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import List, Optional
import yaml

from parrot.bots.database.models import Completeness, TableMetadata
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
class SQLToolkit(DatabaseToolkit):                           # line 61
    exclude_tools: tuple[str, ...] = (...)                    # line 70
    async def search_schema(
        self, search_term, schema_name=None, limit=10,
    ) -> List[TableMetadata]: ...                             # line 106
    async def generate_query(
        self, natural_language, target_tables=None, query_type="SELECT",
    ) -> str: ...                                             # line 137
    async def _search_in_database(
        self, search_term, schema_name=None, limit=10,
    ) -> List[TableMetadata]: ...                             # line 716

# From TASK-1202:
class CachePartition:
    async def get(self, schema, table, *, required, max_age=None) -> Optional[TableMetadata]: ...
    async def search(self, schemas, term, *, completeness_min, max_age=None, limit=20) -> List[TableMetadata]: ...

# From TASK-1203:
class SQLToolkit:
    async def _introspect_table_full(self, schema, table) -> Optional[TableMetadata]: ...
```

### Existing Defects to Remove
```python
# sql.py:125-132 — DELETE the early-return block:
if self.cache_partition is not None:
    target_schemas = [schema_name] if schema_name else self.allowed_schemas
    cached = await self.cache_partition.search_similar_tables(
        target_schemas, search_term, limit=limit
    )
    if cached:
        return cached            # ← REMOVE: must merge with DB results
return await self._search_in_database(search_term, schema_name, limit)


# sql.py:159-165 — REPLACE the cache-only generate_query body:
if target_tables and self.cache_partition:
    for table_name in target_tables:
        for schema in self.allowed_schemas:
            meta = await self.cache_partition.get_table_metadata(schema, table_name)
            if meta:
                context_parts.append(meta.to_yaml_context())
                break           # ← no fallback; replace with describe_table flow
```

### Does NOT Exist
- ~~`SQLToolkit.describe_table`~~ — introduced here.
- ~~`SQLToolkit.list_tables` / `search_tables`~~ — **NOT
  introduced** (Q1 resolution: rename in-place).

---

## Implementation Notes

### Merge + dedupe + sort pattern (search_schema)
```python
target_schemas = [schema_name] if schema_name else self.allowed_schemas
cache_hits = await self.cache_partition.search(
    target_schemas, search_term,
    completeness_min=Completeness.NAME_ONLY, limit=limit,
) if self.cache_partition is not None else []
db_hits = await self._search_in_database(search_term, schema_name, limit)

merged: Dict[Tuple[str, str], TableMetadata] = {}
for m in (*cache_hits, *db_hits):
    key = (m.schema, m.tablename)
    # prefer the one with higher completeness on collision
    if key not in merged or m.completeness > merged[key].completeness:
        merged[key] = m

scored = [(self.cache_partition._calculate_relevance_score(
              m.tablename, m, self.cache_partition._extract_search_keywords(search_term)
          ), m) for m in merged.values()]
scored.sort(key=lambda x: x[0], reverse=True)
return [m for _, m in scored[:limit]]
```
(If `cache_partition is None`, fall back to a no-op scorer that
returns `0.0` for everything and sort is stable on insertion
order.)

### `describe_table` target resolution
`target_tables` entries may arrive as `"schema.table"` or as a
bare `"table"`. Resolution:
1. If `"."` in entry: split and use directly.
2. Else: for each `schema` in `self.allowed_schemas`, try
   `await self.describe_table(schema, entry)` and take the first
   non-`None` result.

### `generate_query` output shape
Per spec §3 Module 4, the function returns a string formatted for
LLM consumption: the templated SELECT skeleton + the per-table
YAML metadata block. Keep it as a single string so the existing
callers (`SQLToolkit.generate_query` → returns `str`) do not break
on type expectations.

### `exclude_tools`
The framework auto-registers every public coroutine on the
toolkit as a tool. Make sure `_introspect_table_full` stays
private (underscore prefix) and `describe_table` is public.
No changes to `exclude_tools` should be needed if naming follows
the convention — but verify by reading sql.py:70 in case the
auto-registration uses an opt-out list.

---

## Acceptance Criteria

- [ ] `search_schema` always queries the DB (no early-return) and
      returns merged + score-sorted results
- [ ] `search_schema` deduplicates by `(schema, tablename)`,
      preferring the higher-completeness entry on collision
- [ ] `describe_table(schema, table)` returns metadata with
      `completeness == Completeness.FULL` for an existing table
- [ ] `describe_table` stores the result in the cache after
      introspection
- [ ] `describe_table` returns `None` for a non-existent table
- [ ] `generate_query(target_tables=[...])` always reads columns
      via `describe_table`, never emits `columns: []` for an
      existing table
- [ ] `generate_query` without `target_tables` calls
      `search_schema` first
- [ ] Existing toolkit tests still pass
- [ ] `pytest packages/ai-parrot/tests/bots/database/test_sql_toolkit_methods.py -v` passes

---

## Test Specification

```python
from unittest.mock import AsyncMock
import pytest

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.bots.database.toolkits.sql import SQLToolkit


def _full(schema, table, cols):
    return TableMetadata(
        schema=schema, tablename=table, table_type="BASE TABLE",
        full_name=f"{schema}.{table}", completeness=Completeness.FULL,
        columns=cols, source="information_schema",
    )


class TestSearchSchema:
    async def test_merges_cache_and_db(self, toolkit_with_mocks):
        tk, cache, db = toolkit_with_mocks
        cache.search.return_value = [
            _full("altice", "store_inventory", [{"name": "x"}]),
            _full("altice", "store_groups", [{"name": "y"}]),
        ]
        db.return_value = [
            _full("pokemon", "stores", [{"name": "state_code"}]),
        ]
        out = await tk.search_schema("stores", limit=10)
        names = {(m.schema, m.tablename) for m in out}
        assert ("pokemon", "stores") in names
        assert ("altice", "store_inventory") in names

    async def test_no_early_return(self, toolkit_with_mocks):
        tk, cache, db = toolkit_with_mocks
        cache.search.return_value = [_full("altice", "store_inventory", [])]
        db.return_value = [_full("pokemon", "stores", [])]
        await tk.search_schema("store")
        db.assert_awaited_once()


class TestDescribeTable:
    async def test_promotes_stub_to_full(self, toolkit_with_stub):
        tk = toolkit_with_stub  # cache holds NAME_ONLY stub for pokemon.stores
        out = await tk.describe_table("pokemon", "stores")
        assert out.completeness == Completeness.FULL


class TestGenerateQuery:
    async def test_calls_describe_per_target(self, toolkit_for_gen):
        tk, describe = toolkit_for_gen
        await tk.generate_query("show forms", target_tables=["a.x", "b.y"])
        assert describe.await_count == 2

    async def test_skeleton_has_real_columns(self, toolkit_for_gen):
        out = await toolkit_for_gen[0].generate_query(
            "x", target_tables=["pokemon.stores"],
        )
        assert "state_code" in out
        assert "SELECT" in out
```

---

## Agent Instructions

1. Confirm TASK-1202 and TASK-1203 are in `sdd/tasks/completed/`.
2. Re-verify line numbers in `sql.py`.
3. Implement.
4. Run unit tests + lint.
5. Move task file to `completed/` and update the per-spec index.
6. Fill in the Completion Note.

---

## Completion Note

Implemented on branch `feat-178-database-toolkit-cache-contract`.

- **`search_schema`** rewritten: drops the early-return cache block; always calls `cache_partition.search()` (new TASK-1202 API) AND `_search_in_database()`; merges by `(schema, tablename)` preferring the higher-completeness entry on collision; sorts descending by `_calculate_relevance_score`; returns top `limit`. Docstring updated to say "identifiers, not data values".
- **`describe_table`** added as new public tool: checks cache with `required=Completeness.FULL`, falls through to `_introspect_table_full` (TASK-1203) on miss, stores the result, returns `None` if table does not exist.
- **`generate_query`** repurposed: resolves `"schema.table"` and bare `"table"` entries via `describe_table`; if `target_tables` is empty uses `search_schema(limit=5)` top-3; renders SELECT skeleton with real column list plus `to_yaml_context()` YAML block; LLM never sees `columns: []` for existing tables.
- 15/15 new tests pass; 81/81 database tests pass; ruff clean.
