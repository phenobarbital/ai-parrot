# TASK-755: Migrate SELECT-heavy read tools to `select_rows` (batch)

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-747, TASK-749, TASK-750, TASK-751, TASK-752, TASK-753, TASK-754
**Assigned-to**: unassigned

---

## Context

Implements **Module 8** of the spec. Batches the simple
single-table-equality SELECTs across all read tools into `select_rows`
calls. Depends on Module 0a (TASK-747) for `column_casts` and `distinct`.
Runs after every write migration so any regression in write paths
surfaces first.

---

## Scope

Migrate the following methods' SELECT sites (single-table equality
only). Complex JOINs / UNIONs / ILIKE / full-text searches **stay on
`execute_query`** as documented exceptions.

### Migrate to `select_rows`
- `get_program` (line 804) — simple WHERE on `auth.programs`.
- `list_programs` (line 824) — `select_rows` with `order_by`, `limit`.
- `get_module` (line 1030).
- `list_modules` (line 1052) — `select_rows(column_casts={"inserted_at":"text",
  "updated_at":"text"})` for the `sort_by_newest=True` path. The
  `(attributes->>'order')::numeric NULLS LAST` sort mode **stays on
  `execute_query`** — documented exception.
- `get_dashboard` (line 1197) — `select_rows` by UUID.
- `list_dashboards` (line 1214).
- `get_widget` (line 1481) — `select_rows` by UUID. The slug-fallback
  path (ILIKE) stays on `execute_query`.
- `list_widgets` (line 1503).
- `list_widget_types` (line 1569).
- `list_widget_categories` (line 1577) →
  `select_rows("navigator.widget_types", columns=["category"],
  distinct=True, order_by=["category"])`.
- `list_clients` (line 1585).
- `list_groups` (line 1596).
- Internal resolvers (`_resolve_program_id`, `_resolve_module_id`,
  `_resolve_dashboard_id`, `_resolve_client_ids`) — only the
  single-table equality branches. `ANY($1::int[])` patterns stay raw.

### Stay on `execute_query` (documented)
- `get_widget_schema` (line 1618) — joins `widget_types` + `widgets_templates`.
- `find_widget_templates` (line 1682) — multi-table join with ILIKE.
- `search_widget_docs` (line 1715) — full-text search.
- `get_full_program_structure` (line 1750) — four-level nested fetch.
- `search` (line 1798) — UNION across entities.

**NOT in scope**: any write tool (already migrated in earlier tasks);
any change to return-shape keys (`columns=[…]` list passed to
`select_rows` MUST match the pre-migration SELECT list byte-for-byte to
avoid silently adding keys downstream clients have not seen).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Rewrite read-tool bodies per list above |
| `packages/ai-parrot-tools/tests/unit/test_navigator_read_tools.py` | CREATE | Per-tool unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.toolkits.postgres import PostgresToolkit
# verified: packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:28
```

### Existing Signatures to Use
```python
async def select_rows(self, table, where=None, columns=None,
    order_by=None, limit=None, conn=None,
    distinct=False, column_casts=None): ...                                # postgres.py:609 (post-TASK-747)
async def execute_query(self, sql, params=None, conn=None): ...            # inherited from SQLToolkit
```

### Does NOT Exist
- ~~`select_rows(where={"col": None})`~~ — None values are stripped
  (Pydantic `exclude_none=True`). Use `execute_query` for `IS NULL`.
- ~~`select_rows(where={"col": [1,2,3]})`~~ — equality-only. Use
  `execute_query` for `= ANY($1::int[])`.
- ~~`select_rows(order_by="…::numeric NULLS LAST")`~~ — expression
  `order_by` not supported. That `list_modules` sort mode stays raw.

---

## Implementation Notes

### Return-Shape Preservation (critical)
For every migrated tool, pass an explicit `columns=[…]` matching the
old SELECT list. `select_rows` otherwise returns every column in the
table — which adds keys downstream agents have never seen.

### Examples
```python
# list_widget_categories (line 1577)
rows = await self.select_rows(
    "navigator.widget_types",
    columns=["category"],
    distinct=True,
    order_by=["category"],
)

# list_modules, sort_by_newest=True
rows = await self.select_rows(
    "navigator.modules",
    where={"program_id": pid},
    columns=[<same list as old SELECT>],
    order_by=["inserted_at DESC"],
    limit=limit,
    column_casts={"inserted_at": "text", "updated_at": "text"},
)

# list_modules, attribute-order sort mode → keep execute_query
# (document why in a code comment)
```

---

## Acceptance Criteria

- [ ] `list_programs`, `get_program`, `get_module`, `list_modules
      (sort_by_newest)`, `get_dashboard`, `list_dashboards`,
      `get_widget (uuid path)`, `list_widgets`, `list_widget_types`,
      `list_widget_categories`, `list_clients`, `list_groups` route
      through `select_rows`.
- [ ] `list_widget_categories` uses `select_rows(distinct=True)`; no raw SQL path.
- [ ] `list_modules(sort_by_newest=True)` uses `column_casts={"inserted_at":"text","updated_at":"text"}`.
- [ ] `list_modules` attribute-order sort mode, `get_widget` slug
      fallback, `get_widget_schema`, `find_widget_templates`,
      `search_widget_docs`, `get_full_program_structure`, and `search`
      stay on `execute_query` (documented in code).
- [ ] Return-shape (dict keys) byte-identical for every migrated tool.
- [ ] Authorization helpers unchanged.
- [ ] `get_tools()` snapshot still green.
- [ ] `pytest packages/ai-parrot-tools/tests/unit/test_navigator_read_tools.py -v` passes.

---

## Test Specification

Required (spec §4):
- `test_list_programs_uses_select_rows`
- `test_list_modules_sort_by_newest_preserved`
- `test_list_modules_column_casts_serializes_timestamps_as_text`
- `test_list_widget_categories_uses_select_rows_distinct`
- `test_get_full_program_structure_still_uses_execute_query`
- `test_search_still_uses_execute_query`

---

## Agent Instructions

Standard. Biggest task of the feature — split commits per method for
bisectable history. Do NOT remove the `_nav_run_query` / `_nav_run_one`
helpers yet; that is TASK-756.
