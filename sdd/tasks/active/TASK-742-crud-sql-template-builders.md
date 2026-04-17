# TASK-742: SQL template builders (pure functions)

**Feature**: FEAT-106 — NavigatorToolkit ↔ PostgresToolkit Interaction
**Spec**: `sdd/specs/navigatortoolkit-postgrestoolkit-interaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

CRUD tool methods on `PostgresToolkit` (TASK-743) emit parameterized SQL
via pure template builders. Keeping these as module-level pure functions
makes them trivially unit-testable without a live DB and lets the
per-instance `_prepared_cache` store only strings (no closures).

Implements **Module 4** of the spec (shares file with TASK-741).

---

## Scope

- Add to `packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py`
  (create if not already created by TASK-741):
  - `_build_insert_sql(schema, table, columns, returning) -> tuple[str, list[str]]`
  - `_build_upsert_sql(schema, table, columns, conflict_cols, update_cols, returning) -> tuple[str, list[str]]`
  - `_build_update_sql(schema, table, set_columns, where_columns, returning) -> tuple[str, list[str]]`
  - `_build_delete_sql(schema, table, where_columns, returning) -> tuple[str, list[str]]`
  - `_build_select_sql(schema, table, columns, where_columns, order_by, limit) -> tuple[str, list[str]]`
- All builders:
  - Use `DatabaseToolkit._validate_identifier` (base.py:167) for **every**
    schema, table, and column name reaching the SQL string.
  - Emit positional placeholders `$1`, `$2`, … (asyncpg-style).
  - Return a deterministic `param_order: list[str]` listing the column
    names in the same order as `$1`, `$2`, … so the caller can build
    the args tuple from the validated data dict.
  - JSON columns: the **template** builders do NOT handle casting — the
    caller passes in `json_cols: frozenset[str]` OR the builders accept a
    `json_cols` parameter and emit `$N::text::jsonb` for those columns.
    Match the brainstorm's decision: **builders take `json_cols` as a
    keyword** so they remain stateless. Verify the exact shape by
    reading the spec's Section 7 "Implementation Notes" jsonb guidance.
- Identifier quoting: every identifier emitted to the SQL string MUST
  pass through `_validate_identifier` AND be wrapped in double quotes
  (`"schema"."table"`). This mirrors the existing pattern in
  `NavigatorToolkit` (today).
- All builders are **pure**: no I/O, no class state, no logging.

**NOT in scope**:
- Calling `QueryValidator.validate_sql_ast` — that happens in TASK-743.
- The `_prepared_cache` dict — TASK-743.
- Upsert-with-auto-SELECT-fallback behavior — TASK-743 (formalized per spec Q2).
- Supporting dialects other than Postgres — Postgres-only for v1.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py` | CREATE or APPEND | Five SQL template builders + constants |
| `tests/unit/test_crud_helpers.py` | CREATE or EXTEND | Test each builder's output SQL + param_order |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
from typing import Optional, List, Tuple, FrozenSet

from parrot.bots.database.toolkits.base import DatabaseToolkit
# verified at: packages/ai-parrot/src/parrot/bots/database/toolkits/__init__.py:9
# Only needed for: DatabaseToolkit._validate_identifier (staticmethod)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
class DatabaseToolkit(AbstractToolkit, ABC):
    @staticmethod
    def _validate_identifier(name: str) -> str:                 # line 167
        """Validate an identifier (schema/table/column) and return it unquoted.

        Raises ValueError on invalid input. Does NOT quote the result —
        the caller is responsible for wrapping in double quotes before
        concatenation into the SQL string.
        """
```

### Does NOT Exist

- ~~A shared `_quote_ident(name)` helper in `base.py`~~ — just `_validate_identifier`. Quote inside each builder with `f'"{name}"'` after validation.
- ~~`asyncpg.escape_identifier`~~ — asyncpg doesn't expose identifier escaping; always use `_validate_identifier`.
- ~~Binding by name (`$name`)~~ — asyncpg uses positional `$N`. The builders MUST emit positional placeholders.
- ~~`ON CONFLICT DO NOTHING` shortcuts~~ — TASK-743 handles the DO-NOTHING path by calling upsert with `update_cols=[]` and falling back; the builder still emits `DO UPDATE SET` even if `update_cols` is empty (it can legitimately be a no-op — verify PG accepts `DO UPDATE SET col = EXCLUDED.col` with an empty SET is NOT valid; omit the DO clause entirely if the list is empty and emit `DO NOTHING`).

---

## Implementation Notes

### Pattern to Follow — `_build_insert_sql`

```python
def _build_insert_sql(
    schema: str,
    table: str,
    columns: List[str],
    returning: Optional[List[str]] = None,
    json_cols: FrozenSet[str] = frozenset(),
) -> Tuple[str, List[str]]:
    s = DatabaseToolkit._validate_identifier(schema)
    t = DatabaseToolkit._validate_identifier(table)
    cols = [DatabaseToolkit._validate_identifier(c) for c in columns]

    placeholders = []
    for i, c in enumerate(cols, start=1):
        if c in json_cols:
            placeholders.append(f"${i}::text::jsonb")
        else:
            placeholders.append(f"${i}")

    col_list = ", ".join(f'"{c}"' for c in cols)
    vals = ", ".join(placeholders)
    sql = f'INSERT INTO "{s}"."{t}" ({col_list}) VALUES ({vals})'
    if returning:
        ret = ", ".join(f'"{DatabaseToolkit._validate_identifier(r)}"' for r in returning)
        sql += f" RETURNING {ret}"

    return sql, list(columns)
```

### Pattern — `_build_upsert_sql`

```sql
INSERT INTO "schema"."table" ("a", "b", "c") VALUES ($1, $2, $3)
ON CONFLICT ("a") DO UPDATE SET "b" = EXCLUDED."b", "c" = EXCLUDED."c"
RETURNING "id";
```

- `conflict_cols` must be non-empty (TASK-743 defaults to `primary_keys`).
- `update_cols`: if empty → emit `ON CONFLICT (…) DO NOTHING`.
- Otherwise → emit `DO UPDATE SET "col" = EXCLUDED."col", …` for each in `update_cols`.

### Pattern — `_build_update_sql`

```sql
UPDATE "schema"."table"
   SET "a" = $1, "b" = $2
 WHERE "id" = $3
RETURNING "id";
```

- `param_order = set_columns + where_columns`.
- Reject empty `where_columns` with `ValueError` — TASK-743 enforces PK-in-where, but defensively catch empty-WHERE here too.

### Pattern — `_build_delete_sql`

```sql
DELETE FROM "schema"."table" WHERE "id" = $1 RETURNING "id";
```

- Reject empty `where_columns` with `ValueError`.

### Pattern — `_build_select_sql`

```sql
SELECT "id", "name" FROM "schema"."table"
 WHERE "a" = $1 AND "b" = $2
 ORDER BY "name" ASC
 LIMIT 10;
```

- `columns=None` → emit `SELECT *`.
- `where_columns=None/[]` → omit WHERE.
- `order_by` entries: each entry may be `"col"` or `"col ASC"` / `"col DESC"`.
  Split, validate the identifier, re-join with the direction. Reject any
  direction other than ASC/DESC.
- `limit` is a Python int inlined directly into the SQL (safe — caller
  passes it literally; validate it's a non-negative int).

### Key Constraints

- NO f-string concatenation of user values. Identifiers only, after validation.
- `param_order` MUST be `list[str]` and match the `$N` order.
- Every builder returns `(sql, param_order)` — no exceptions.
- Functions MUST NOT call the database. Unit tests should run without
  `asyncdb`, without a DSN, without any fixtures beyond plain lists.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` — bespoke SQL assembly being replaced (lines 600–700 have good examples of what NOT to copy, to avoid duplication)
- `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py:167` — `_validate_identifier`
- `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py:293` — `_check_query_safety` (reference for how we currently vet SQL)

---

## Acceptance Criteria

- [ ] All 5 builders implemented in `_crud.py`
- [ ] Each builder returns `(sql: str, param_order: list[str])`
- [ ] INSERT emits `RETURNING` clause when `returning` is non-empty, omits otherwise
- [ ] UPSERT with `conflict_cols=None` → `ValueError` (caller must pass PKs)
- [ ] UPSERT with `update_cols=[]` → `ON CONFLICT (…) DO NOTHING`
- [ ] UPDATE/DELETE with empty `where_columns` → `ValueError`
- [ ] JSON columns emit `$N::text::jsonb` casts in INSERT/UPSERT/UPDATE
- [ ] Composite conflict target: `ON CONFLICT ("a", "b") DO UPDATE SET "c" = EXCLUDED."c"`
- [ ] `_validate_identifier` called on every schema/table/column name
- [ ] `pytest tests/unit/test_crud_helpers.py -v` passes (including the TASK-741 tests)
- [ ] No I/O in any builder — verified by tests that don't use `asyncio`

---

## Test Specification

```python
# tests/unit/test_crud_helpers.py — extend file created by TASK-741
import pytest
from parrot.bots.database.toolkits._crud import (
    _build_insert_sql,
    _build_upsert_sql,
    _build_update_sql,
    _build_delete_sql,
    _build_select_sql,
)


class TestBuildInsertSql:
    def test_basic_no_returning(self):
        sql, params = _build_insert_sql("public", "t", ["a", "b"])
        assert sql == 'INSERT INTO "public"."t" ("a", "b") VALUES ($1, $2)'
        assert params == ["a", "b"]

    def test_with_returning(self):
        sql, params = _build_insert_sql("public", "t", ["a"], returning=["id"])
        assert sql.endswith('RETURNING "id"')

    def test_jsonb_cast(self):
        sql, _ = _build_insert_sql(
            "public", "t", ["a", "data"], json_cols=frozenset({"data"})
        )
        assert "$2::text::jsonb" in sql


class TestBuildUpsertSql:
    def test_conflict_cols_required(self):
        with pytest.raises(ValueError):
            _build_upsert_sql("public", "t", ["a"], conflict_cols=None, update_cols=["a"])

    def test_explicit_conflict_cols(self):
        sql, _ = _build_upsert_sql(
            "public", "t",
            columns=["a", "b", "c"],
            conflict_cols=["a"],
            update_cols=["b", "c"],
        )
        assert 'ON CONFLICT ("a")' in sql
        assert '"b" = EXCLUDED."b"' in sql
        assert '"c" = EXCLUDED."c"' in sql

    def test_composite_conflict(self):
        sql, _ = _build_upsert_sql(
            "public", "t",
            columns=["a", "b", "c"],
            conflict_cols=["a", "b"],
            update_cols=["c"],
        )
        assert 'ON CONFLICT ("a", "b")' in sql

    def test_do_nothing_when_update_cols_empty(self):
        sql, _ = _build_upsert_sql(
            "public", "t",
            columns=["a", "b"],
            conflict_cols=["a"],
            update_cols=[],
        )
        assert 'DO NOTHING' in sql
        assert 'DO UPDATE' not in sql


class TestBuildUpdateSql:
    def test_basic(self):
        sql, params = _build_update_sql(
            "public", "t", set_columns=["a", "b"], where_columns=["id"]
        )
        assert '"a" = $1' in sql
        assert '"b" = $2' in sql
        assert '"id" = $3' in sql
        assert params == ["a", "b", "id"]

    def test_jsonb_cast(self):
        sql, _ = _build_update_sql(
            "public", "t",
            set_columns=["data"],
            where_columns=["id"],
            json_cols=frozenset({"data"}),
        )
        assert "$1::text::jsonb" in sql

    def test_empty_where_rejects(self):
        with pytest.raises(ValueError):
            _build_update_sql("public", "t", set_columns=["a"], where_columns=[])


class TestBuildDeleteSql:
    def test_basic(self):
        sql, params = _build_delete_sql("public", "t", where_columns=["id"])
        assert 'DELETE FROM "public"."t" WHERE "id" = $1' in sql
        assert params == ["id"]

    def test_with_returning(self):
        sql, _ = _build_delete_sql("public", "t", where_columns=["id"], returning=["id"])
        assert 'RETURNING "id"' in sql


class TestBuildSelectSql:
    def test_with_where_and_order(self):
        sql, params = _build_select_sql(
            "public", "t",
            columns=["a", "b"],
            where_columns=["a"],
            order_by=["b DESC"],
            limit=10,
        )
        assert 'SELECT "a", "b"' in sql
        assert '"a" = $1' in sql
        assert 'ORDER BY "b" DESC' in sql
        assert "LIMIT 10" in sql
        assert params == ["a"]

    def test_select_star_when_no_columns(self):
        sql, _ = _build_select_sql("public", "t", columns=None, where_columns=None)
        assert sql.startswith('SELECT * FROM "public"."t"')
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — focus on Section 2 (new public interfaces) and Section 7 (jsonb cast guidance)
2. **Check dependencies** — none (pure functions)
3. **Verify the Codebase Contract** — confirm `_validate_identifier` still at base.py:167
4. **Coordinate with TASK-741** — the same `_crud.py` file hosts both. If TASK-741 ran first, APPEND; otherwise CREATE the file with all content.
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** per scope
7. **Verify** all acceptance criteria
8. **Move this file** to `tasks/completed/TASK-742-crud-sql-template-builders.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
