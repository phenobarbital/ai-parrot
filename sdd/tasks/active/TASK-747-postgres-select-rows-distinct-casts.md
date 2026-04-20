# TASK-747: Extend `PostgresToolkit.select_rows` with `distinct` + `column_casts`

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 0a** of the spec. Two NavigatorToolkit read tools
(`list_modules`, `list_widget_categories`) cannot migrate to
`select_rows` until `PostgresToolkit.select_rows` supports per-column
casts (Q2 resolution) and `DISTINCT` (Q4 resolution). This task lands
those additions **before** any Navigator work begins. Additive and
backwards-compatible.

---

## Scope

- Extend `PostgresToolkit.select_rows` signature with:
  - `distinct: bool = False` → emits `SELECT DISTINCT`
  - `column_casts: Optional[Dict[str, str]] = None` → emits `col::<type> AS col`
- Extend `_build_select_sql` in `_crud.py` with matching parameters.
- Add a cast-type whitelist: `{"text", "uuid", "json", "jsonb",
  "integer", "bigint", "numeric", "timestamp", "date"}`. Non-whitelisted
  cast type → `ValueError("unsupported cast type: ...")`.
- When `columns is None` and `column_casts` is set, expand `columns` to
  the full list from `TableMetadata.columns` so cast can be applied in
  the right position.
- When `columns` is explicit, every `column_casts` key MUST appear in
  `columns` — else `ValueError`.
- Update `_get_or_build_template` cache key to include `distinct` and a
  deterministic hash of `column_casts` (sorted `(col, cast)` tuple).

**NOT in scope**: any NavigatorToolkit change; any write-side CRUD
method change; any schema change. Pure additive extension to
`select_rows` + helper.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py` | MODIFY | Extend `select_rows` signature + pass new args down |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py` | MODIFY | Extend `_build_select_sql`; add cast whitelist; update cache-key |
| `packages/ai-parrot/tests/unit/test_postgres_toolkit.py` | MODIFY | Add distinct/column_casts tests |
| `packages/ai-parrot/tests/unit/test_crud_helpers.py` | MODIFY (if exists) | Unit tests for `_build_select_sql` extension |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.toolkits.postgres import PostgresToolkit
# verified: packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:28
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    def _get_or_build_template(self, ...) -> ...:                # line 258
    async def select_rows(                                       # line 609
        self,
        table: str,
        where: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
        order_by: Optional[List[str]] = None,
        limit: Optional[int] = None,
        conn: Optional[Any] = None,
    ) -> List[Dict[str, Any]]: ...

# packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py
def _build_select_sql(...):                                      # line 360
```

### Does NOT Exist
- ~~`select_rows(where={"col": {"op": "in", "value": [...]}})`~~ — equality-only `where`.
- ~~`select_rows(where={"col": None})`~~ — `None` values stripped by Pydantic `exclude_none=True`.
- ~~A pre-existing cast whitelist~~ — this task introduces it.

---

## Implementation Notes

### Cast Whitelist
Place next to `_build_select_sql` in `_crud.py`:
```python
_SELECT_CAST_WHITELIST = frozenset({
    "text", "uuid", "json", "jsonb",
    "integer", "bigint", "numeric",
    "timestamp", "date",
})
```

### SQL Emission
- `distinct=True` → `SELECT DISTINCT ` prefix (instead of `SELECT `).
- `column_casts={"inserted_at": "text"}` with `columns=["module_id", "inserted_at"]`
  → `SELECT module_id, inserted_at::text AS inserted_at FROM …`.

### Cache Key
Existing `_get_or_build_template` cache key → extend with
`("distinct", bool(distinct))` and `("casts", tuple(sorted(column_casts.items())))`
so `distinct=True` templates don't collide with `distinct=False`.

### Backwards Compatibility
Calling `select_rows` without the new kwargs MUST produce byte-identical
SQL to the pre-task baseline. Pin this with a snapshot test.

---

## Acceptance Criteria

- [ ] `select_rows(distinct=True)` emits SQL starting with `SELECT DISTINCT`.
- [ ] `select_rows(column_casts={"col": "text"})` emits `col::text AS col` in the SELECT list.
- [ ] Unknown cast type raises `ValueError("unsupported cast type: ...")`.
- [ ] `column_casts` key not present in `columns` raises `ValueError`.
- [ ] Omitting both new params → SQL identical to pre-task baseline (snapshot test).
- [ ] `_prepared_cache` / `_get_or_build_template` key differs between `distinct=True` and `distinct=False`.
- [ ] `pytest packages/ai-parrot/tests/unit/test_postgres_toolkit.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/database/toolkits/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_postgres_toolkit.py

class TestSelectRowsDistinct:
    async def test_select_rows_distinct_emits_select_distinct(self, toolkit):
        sql, _ = toolkit._get_or_build_template(
            "select", "navigator.widget_types",
            columns=["category"], distinct=True,
        )
        assert sql.startswith("SELECT DISTINCT ")

    async def test_prepared_cache_key_distinct_not_shared(self, toolkit):
        k1 = toolkit._cache_key(..., distinct=True)
        k2 = toolkit._cache_key(..., distinct=False)
        assert k1 != k2


class TestSelectRowsColumnCasts:
    async def test_emits_cast_in_select_list(self, toolkit):
        sql, _ = toolkit._get_or_build_template(
            "select", "navigator.modules",
            columns=["module_id", "inserted_at"],
            column_casts={"inserted_at": "text"},
        )
        assert "inserted_at::text AS inserted_at" in sql

    async def test_rejects_unknown_cast_type(self, toolkit):
        with pytest.raises(ValueError, match="unsupported cast type"):
            toolkit._get_or_build_template(
                "select", "navigator.modules",
                columns=["inserted_at"],
                column_casts={"inserted_at": "bogus"},
            )

    async def test_rejects_cast_for_column_not_in_columns(self, toolkit):
        with pytest.raises(ValueError):
            toolkit._get_or_build_template(
                "select", "navigator.modules",
                columns=["module_id"],
                column_casts={"inserted_at": "text"},
            )


class TestBackCompat:
    async def test_no_new_params_sql_identical(self, toolkit, snapshot):
        sql, _ = toolkit._get_or_build_template(
            "select", "navigator.modules",
            columns=["module_id", "module_name"],
        )
        snapshot.assert_match(sql)
```

---

## Agent Instructions

Standard: read spec, verify contract, implement, test, move to `completed/`,
update index.
