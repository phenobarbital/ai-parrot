# Feature Specification: NavigatorToolkit Method Migration to PostgresToolkit CRUD

**Feature ID**: FEAT-107
**Date**: 2026-04-17
**Author**: Javier León
**Status**: draft
**Target version**: next minor

**Builds on**: [`FEAT-106 — navigatortoolkit-postgrestoolkit-interaction`](./navigatortoolkit-postgrestoolkit-interaction.spec.md) (merged — `PostgresToolkit` now owns `insert_row` / `upsert_row` / `update_row` / `delete_row` / `select_rows` / `transaction` / `reload_metadata`).

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-106 refactored `NavigatorToolkit` to inherit from `PostgresToolkit` and
migrated the pool + DB plumbing to the parent. However, the **bodies of the
tool methods themselves still drive every write through private helpers that
assemble raw SQL strings**:

- `_nav_run_query` (toolkit.py:157) — raw SELECT via `conn.query`
- `_nav_run_one` (toolkit.py:165) — raw SELECT via `conn.queryrow`
- `_nav_execute` (toolkit.py:173) — raw INSERT/UPDATE via `conn.execute`

Grepping the file shows **~56 call sites** using these helpers across 18 LLM
tools. Every write path today is a hand-built `INSERT INTO … VALUES …
ON CONFLICT … DO UPDATE SET … = EXCLUDED.…` string with inline
`$N::text::jsonb` casts, duplicated between the fresh-create branch and the
idempotent re-run branch of `create_program` / `create_module`. The UPDATE
surface is the one exception: `_nav_build_update` already delegates to
`PostgresToolkit.update_row` (FEAT-106/TASK-744).

The consequences:

1. **Safety bypass.** Raw `_nav_execute("INSERT … ON CONFLICT …")` skips the
   whitelist enforcement, Pydantic input validation, `QueryValidator`
   PK-in-WHERE check, and prepared-statement caching that `PostgresToolkit`
   now offers via its CRUD primitives.
2. **Drift risk.** Column renames in `auth.programs`, `navigator.modules`,
   `navigator.dashboards`, or `navigator.widgets` are caught only at SQL
   execute time — no compile-time or Pydantic-level protection.
3. **Transactional gaps.** Multi-table write flows (`create_program` →
   `auth.programs` + `auth.program_clients` + `auth.program_groups` +
   cascaded `navigator.client_modules` + `navigator.modules_groups`) loop
   through `_nav_execute` without a surrounding `transaction()`. A mid-flow
   failure leaves the DB in an inconsistent state.
4. **Lost cache locality.** Each raw INSERT re-parses the SQL on asyncpg's
   side; `PostgresToolkit._prepared_cache` is unused by the Navigator paths.
5. **Maintenance cost.** The ~56 raw SQL strings are the single largest
   source of future bugs; converging them on five CRUD primitives is the
   cheapest path to correctness.

### Goals

- **G1** — Migrate every write site in `NavigatorToolkit` from
  `_nav_execute` to `self.insert_row(...)` or `self.upsert_row(...)`,
  preserving current `ON CONFLICT` semantics (DO NOTHING vs.
  DO UPDATE SET active = EXCLUDED.active).
- **G2** — Migrate every SELECT site currently using `_nav_run_query` /
  `_nav_run_one` to `self.select_rows(...)` **when the query is a pure
  single-table equality filter**. Joins, subqueries, and complex search
  queries stay on `self.execute_query(...)` (the `SQLToolkit`-inherited
  raw-SQL tool) rather than being re-expressed.
- **G3** — Wrap every multi-table write flow in
  `async with self.transaction() as tx:` and pass `conn=tx` to every CRUD
  call inside the block, so partial failures roll back atomically.
- **G4** — Preserve the `confirm_execution` guardrail flow exactly: when
  `confirm_execution=False` the method still returns a
  `{"status": "confirm_execution", …}` plan dict *without* touching the
  database. Plans now include the templated SQL produced by
  `_get_or_build_template` instead of hand-concatenated strings.
- **G5** — Preserve the full LLM-facing tool surface: tool names, tool
  prefixes, input shapes (Pydantic schemas in `navigator/schemas.py`),
  return dict shapes, and error messages. This migration is **strictly
  internal**; `NavigatorToolkit.get_tools()` output must be byte-identical
  to the pre-migration baseline.
- **G6** — Remove `_nav_run_query`, `_nav_run_one`, `_nav_execute`, and
  `_nav_build_update` once all call sites have been migrated. These
  helpers become dead code at the end of the migration.
- **G7** — Retain all authorization guardrails
  (`_check_program_access`, `_check_module_access`, `_check_client_access`,
  `_check_dashboard_access`, `_check_widget_access`, `_check_write_access`,
  `_require_superuser`, `_load_user_permissions`, `_apply_scope_filter`)
  byte-for-byte. They are orthogonal to the migration and must stay.
- **G8** — Add regression tests capturing the `get_tools()` tool-name
  baseline and the `confirm_execution=False` plan-dict shape before
  migrating any method, so the migration cannot silently change either.

### Non-Goals (explicitly out of scope)

- **Altering Pydantic input schemas** (`schemas.py`). LLM-facing input
  contract stays hand-written and unchanged — descriptions, defaults,
  `@model_validator(mode="before")` coercions, and the
  `confirm_execution` field all stay.
- **Rewriting complex SELECTs as `select_rows`.** Tools like
  `get_full_program_structure`, `search`, `find_widget_templates`, and the
  widget-template join in `get_widget_schema` use multi-table JOINs or
  UNIONs that `select_rows` does not support by design. These continue
  to go through `self.execute_query(sql, …)` — the raw-SQL tool inherited
  from `SQLToolkit`.
- **Adding new LLM tools.** The public surface is frozen. No new
  `nav_*` tools are introduced.
- **Touching `_load_user_permissions` or authorization helpers.** Their
  SQL is read-only introspection against `auth.user_groups` etc. and is
  not on the critical write path.
- **Changing the `confirm_execution` contract.** The field, its default
  (`False`), its description, and the returned plan-dict schema stay
  exactly as today.
- **Removing the `tool_prefix = "nav"` override.** Tool names (`nav_*`)
  are part of the deployed contract and stay.
- **Cascading changes into dependent agents** (e.g., external Navigator
  agent server). Those clients consume `NavigatorToolkit` via its LLM
  tool surface, which this migration preserves.
- **Migrating `auth.*` or `navigator.*` SELECTs that are not table
  whitelisted** (e.g., `auth.user_groups` joined with `auth.groups`).
  These remain on raw SQL.

---

## 2. Architectural Design

### Overview

The migration is mechanical and method-scoped. Each LLM tool in
`NavigatorToolkit` becomes an independent migration task that:

1. Replaces `self._nav_execute(INSERT …)` calls with
   `self.insert_row(table, data, returning=[...], conn=tx)` or
   `self.upsert_row(table, data, conflict_cols=[...], update_cols=[...],
   returning=[...], conn=tx)`.
2. Replaces `self._nav_run_one(SELECT * FROM t WHERE pk = $1)` with
   `rows = await self.select_rows(t, where={"pk": val}, limit=1)` → `row = rows[0] if rows else None`.
3. Replaces `self._nav_run_query(SELECT cols FROM t WHERE ...)` with
   `self.select_rows(t, where=..., columns=..., order_by=..., limit=...)`.
4. Wraps any method that writes to **two or more** tables in
   `async with self.transaction() as tx:` and threads `conn=tx` through
   every CRUD call.
5. Preserves the `if not confirm_execution:` guardrail branch exactly:
   the plan dict is built *before* any DB write, and the function returns
   without acquiring a transaction.

No new classes, no new modules, no new public API — only internal method
body rewrites.

### Component Diagram (unchanged)

```
┌─────────────────────────────────────────────────────────────┐
│ NavigatorToolkit(PostgresToolkit)   (tool_prefix = "nav")   │
│                                                             │
│  LLM-facing tools: nav_create_program / nav_create_module / │
│                    nav_create_dashboard / nav_create_widget │
│                    nav_update_* / nav_get_* / nav_list_*    │
│                                                             │
│  Authorization guardrails (unchanged):                      │
│    _check_program_access, _check_module_access,             │
│    _check_write_access, _require_superuser,                 │
│    _load_user_permissions, _apply_scope_filter              │
└────────────────────┬────────────────────────────────────────┘
                     │ delegates ALL writes to
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ PostgresToolkit (FEAT-106, already merged)                  │
│                                                             │
│   insert_row / upsert_row / update_row / delete_row /       │
│   select_rows / transaction() / reload_metadata()           │
│                                                             │
│   _prepared_cache (per-instance template cache)             │
│   _resolve_table (whitelist enforcement)                    │
│   _get_or_build_pydantic_model (dynamic Pydantic)           │
│   QueryValidator.validate_sql_ast (PK-in-WHERE for U/D)     │
└─────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PostgresToolkit.insert_row` | called by | every single-row INSERT site in NavigatorToolkit |
| `PostgresToolkit.upsert_row` | called by | every `INSERT … ON CONFLICT …` site (currently raw strings) |
| `PostgresToolkit.update_row` | called by | already used via `_nav_build_update`; direct calls added where it fits |
| `PostgresToolkit.select_rows` | called by | every single-table equality SELECT |
| `PostgresToolkit.execute_query` | called by | inherited raw-SQL fallback for JOINs / UNIONs / subqueries |
| `PostgresToolkit.transaction` | called by | every multi-table write method wraps its body |
| `_resolve_table` | indirectly | enforces `self._NAVIGATOR_TABLES` whitelist on every CRUD call |
| `_acquire_asyncdb_connection` | indirectly | parent-managed pool connections |
| `navigator/schemas.py` | no change | Pydantic input schemas frozen |
| `parrot.security.QueryValidator` | no change | already used by `update_row` / `delete_row` via parent |

### Data Models

No new data models. All CRUD calls pass plain `dict[str, Any]` payloads
validated by the dynamic Pydantic model that `PostgresToolkit` builds from
`TableMetadata.columns` per table.

### New Public Interfaces

None. The public tool surface is frozen (see Non-Goals and Acceptance
Criteria).

### Migration Pattern (reference)

Before (raw INSERT with inline cast, outside a transaction):
```python
row = await self._nav_run_one(
    """INSERT INTO auth.programs
       (program_name, program_slug, description, attributes, created_by)
       VALUES ($1,$2,$3,$4::text::jsonb,'navigator_toolkit')
       RETURNING program_id, program_slug""",
    [program_name, program_slug, description, self._jsonb(attributes)]
)
pid = row["program_id"]

for cid in client_ids:
    await self._nav_execute(
        "INSERT INTO auth.program_clients "
        "(program_id, client_id, program_slug, client_slug, active) "
        "VALUES ($1,$2,$3,$4,true) ON CONFLICT DO NOTHING",
        [pid, cid, program_slug, client_slugs_map.get(cid, program_slug)]
    )
```

After (CRUD primitives inside a transaction):
```python
async with self.transaction() as tx:
    row = await self.insert_row(
        "auth.programs",
        data={
            "program_name": program_name,
            "program_slug": program_slug,
            "description": description,
            "attributes": attributes,
            "created_by": "navigator_toolkit",
        },
        returning=["program_id", "program_slug"],
        conn=tx,
    )
    pid = row["program_id"]

    for cid in client_ids:
        await self.upsert_row(
            "auth.program_clients",
            data={
                "program_id": pid,
                "client_id": cid,
                "program_slug": program_slug,
                "client_slug": client_slugs_map.get(cid, program_slug),
                "active": True,
            },
            conflict_cols=["program_id", "client_id"],
            update_cols=[],   # DO NOTHING on conflict
            conn=tx,
        )
```

---

## 3. Module Breakdown

Each module below maps 1:1 to a TASK-NNN in `/sdd-task` decomposition.
All modules touch the same file
(`packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`) — they
run **sequentially** in a single worktree (see Worktree Strategy).

### Module 1: Baseline regression tests (must land first)

- **Path**: `packages/ai-parrot-tools/tests/unit/test_navigator_toolkit_baseline.py` (new)
- **Responsibility**:
  - Capture current `NavigatorToolkit.get_tools()` tool-name list and
    tool-description strings as a fixture.
  - For every write tool (`create_*`, `update_*`, `clone_dashboard`,
    `assign_module_to_*`), assert that invoking with `confirm_execution=False`
    (or default) returns `{"status": "confirm_execution", ...}` and makes
    **zero** calls to the underlying asyncdb connection (verified by
    passing a `unittest.mock.AsyncMock()` connection and asserting
    `mock.execute.call_count == 0`, etc.).
  - Capture one invocation of `confirm_execution=True` for
    `create_program` against a mocked `PostgresToolkit.insert_row` /
    `upsert_row` / `transaction` to snapshot the call arguments as the
    "target shape" for later migration tasks.
- **Depends on**: nothing — establishes the safety net before any body
  rewrite.

### Module 2: `create_program` migration

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
  (method at line 657)
- **Responsibility**:
  - Wrap entire DB-writing body in `async with self.transaction() as tx:`.
  - Replace the `SELECT client_id, client_slug FROM auth.clients WHERE
    client_id = ANY($1::int[])` at line 689 with `select_rows("auth.clients",
    where=..., columns=["client_id", "client_slug"])`. Because
    `select_rows` uses equality WHERE only (no `= ANY`), fall back to
    `self.execute_query(...)` for this single query and document why.
  - Replace the idempotency lookup at line 704 with
    `self.select_rows("auth.programs", where={"program_slug": …},
    columns=["program_id", "program_slug"], limit=1)`.
  - Replace the cascaded module-list fetch at line 712 with
    `self.select_rows("navigator.modules", where={"program_id": pid},
    columns=["module_id"])`.
  - Replace `INSERT INTO auth.program_clients … ON CONFLICT DO NOTHING`
    (lines 720-724, 773-777) with `self.upsert_row("auth.program_clients",
    data={…}, conflict_cols=["program_id", "client_id"],
    update_cols=[], conn=tx)`.
  - Replace `INSERT INTO navigator.client_modules … ON CONFLICT … DO UPDATE
    SET active = EXCLUDED.active` (lines 726-730) with
    `self.upsert_row(..., conflict_cols=["client_id","program_id","module_id"],
    update_cols=["active"], conn=tx)`.
  - Replace `INSERT INTO auth.program_groups ((SELECT COALESCE(MAX(...))...),
    $1, $2, $3, now()) ON CONFLICT DO NOTHING` (lines 733-738, 779-784).
    The `gprogram_id = SELECT COALESCE(MAX(...))+1` expression cannot be
    expressed through `upsert_row` data dict — it requires a SQL
    sub-expression. For this INSERT only, call
    `self.execute_query(sql, …)` with the original string. Document this
    explicitly as an exception.
  - Replace `INSERT INTO navigator.modules_groups … ON CONFLICT … DO UPDATE
    SET active = EXCLUDED.active` (lines 741-745) with `upsert_row`.
  - Replace the main `INSERT INTO auth.programs … RETURNING program_id,
    program_slug` at line 759 with `self.insert_row("auth.programs",
    data={…}, returning=["program_id","program_slug"], conn=tx)`.
  - Keep `setval(pg_get_serial_sequence('auth.programs', 'program_id'),
    …)` at line 754 as `self.execute_query(…)` — it's a sequence-repair
    side effect, not a row operation.
  - **`confirm_execution=False` branch stays identical** (lines 695-701).
- **Depends on**: Module 1.

### Module 3: `create_module` migration

- **Path**: `toolkit.py` method at line 850
- **Responsibility**:
  - Same pattern as Module 2: wrap in `transaction()`, convert the main
    `INSERT INTO navigator.modules … RETURNING module_id` to `insert_row`.
  - Convert idempotency lookup (line 924) and existing-assignments
    upserts (lines 933-952, 984-1003) to `upsert_row` with
    `conn=tx`.
  - Convert `SELECT program_slug FROM auth.programs WHERE program_id = $1`
    (line 880) and the `SELECT client_slug FROM auth.clients …` block
    (line 903) to `select_rows`.
  - Preserve the Home-module slug convention (`module_slug = program_slug`
    when the canonical name is "Home"), the `{program_slug}_{slug}`
    prefix rule, and the `description = description or module_name.title()`
    fallback — these are untouched business rules that live **above** the
    DB write.
  - `confirm_execution=False` branch unchanged (lines 915-920).
- **Depends on**: Module 1. Runs after Module 2 in the same worktree.

### Module 4: `create_dashboard` migration

- **Path**: `toolkit.py` method at line 1088
- **Responsibility**:
  - Wrap body in `transaction()` (currently single INSERT, but will grow
    if cascading assignments become necessary).
  - Convert the idempotency lookup at line 1135 and the main INSERT at
    line 1157 (20-column INSERT with multiple `::text::jsonb` casts) to
    `insert_row("navigator.dashboards", data={…}, returning=[…], conn=tx)`.
  - The dynamic Pydantic model built from `TableMetadata.columns` handles
    the `::text::jsonb` casts internally via `_prepare_args` and
    `_json_cols_for`, so the hand-written `$15::text::jsonb,
    $16::text::jsonb, $17::text::jsonb, $18, $19::text::jsonb,
    $20::text::jsonb` template is removed.
  - `confirm_execution=False` branch unchanged (lines 1126-1131).
- **Depends on**: Module 1.

### Module 5: `clone_dashboard` migration

- **Path**: `toolkit.py` method at line 1244
- **Responsibility**:
  - Convert source-dashboard fetch (line 1265), new dashboard INSERT
    (line 1282), and widget-fan-out INSERT loop (line 1298) to CRUD
    primitives.
  - Wrap the fan-out in `transaction()` with `conn=tx` threaded through
    every row write, so a partial failure rolls back the clone cleanly.
  - Preserve the `_check_write_access(target_program_id)` call at
    line 1263 and the source-program access check at line 1270.
  - `confirm_execution=False` branch unchanged (lines 1274-1279).
- **Depends on**: Module 4 (relies on the same Pydantic dashboard model
  being warm / cached).

### Module 6: `create_widget` migration

- **Path**: `toolkit.py` method at line 1332
- **Responsibility**:
  - Convert the widget INSERT at line 1389 (19-column insert with six
    `::text::jsonb` casts and one explicit `::varchar` cast) to
    `insert_row("navigator.widgets", data={…}, returning=["widget_id",
    "widget_type"], conn=tx)`.
  - The single UPDATE at line 1429 that merges the new widget into the
    parent dashboard's `widget_location` JSON (`UPDATE navigator.dashboards
    SET attributes = $1::text::jsonb WHERE dashboard_id = $2`) becomes
    `self.update_row("navigator.dashboards", data={"attributes": merged},
    where={"dashboard_id": did}, conn=tx)`.
  - Wrap both writes in a single `transaction()` so a mis-merge rolls
    back the widget insert.
  - `confirm_execution=False` branch unchanged (lines 1381-1386).
- **Depends on**: Module 1.

### Module 7: `assign_module_to_client` + `assign_module_to_group` migration

- **Paths**:
  - `toolkit.py::assign_module_to_client` (line 1536)
  - `toolkit.py::assign_module_to_group` (line 1551)
- **Responsibility**:
  - Both methods are single-table upserts today. Convert each to
    `self.upsert_row(...)` with the correct `conflict_cols` and
    `update_cols=["active"]` to preserve current `ON CONFLICT … DO UPDATE
    SET active = EXCLUDED.active` semantics.
  - No transaction wrapper needed (single-table write).
  - `confirm_execution=False` branch stays.
- **Depends on**: Module 1.

### Module 8: SELECT-heavy read tools migration (batch)

- **Path**: `toolkit.py`
- **Responsibility**: Convert single-table equality SELECTs in the
  following methods to `select_rows`. Complex JOINs / UNIONs stay on
  `execute_query`:
  - `get_program` (line 804) — simple WHERE on `auth.programs` → `select_rows`.
  - `list_programs` (line 824) — `select_rows` with `order_by` and `limit`.
  - `get_module` (line 1030) — `select_rows`.
  - `list_modules` (line 1052) — preserve the `ORDER BY inserted_at DESC` /
    `ORDER BY program_id, (attributes->>'order')::numeric NULLS LAST`
    switch via `order_by=` parameter.
  - `get_dashboard` (line 1197) — `select_rows` by UUID.
  - `list_dashboards` (line 1214) — `select_rows`.
  - `get_widget` (line 1481) — `select_rows` by UUID; slug fallback stays
    via `execute_query` (ILIKE search).
  - `list_widgets` (line 1503) — `select_rows`.
  - `list_widget_types` (line 1569) — `select_rows("navigator.widget_types")`.
  - `list_widget_categories` (line 1577) — `select_rows` on
    `navigator.widget_types` with DISTINCT → keep as `execute_query`
    (DISTINCT not supported by `select_rows`).
  - `list_clients` (line 1585) — `select_rows`.
  - `list_groups` (line 1596) — `select_rows`.
  - `get_widget_schema` (line 1618) — **stays on `execute_query`** (joins
    `widget_types` + `widgets_templates`).
  - `find_widget_templates` (line 1682) — **stays on `execute_query`**
    (multi-table join with ILIKE across template description).
  - `search_widget_docs` (line 1715) — **stays on `execute_query`**
    (full-text search or similar).
  - `get_full_program_structure` (line 1750) — **stays on `execute_query`**
    (four-level nested fetch).
  - `search` (line 1798) — **stays on `execute_query`** (UNION across entities).
  - Internal resolvers (`_resolve_program_id`, `_resolve_module_id`,
    `_resolve_dashboard_id`, `_resolve_client_ids`) — convert the
    ones with single-table equality filters; leave `ANY($1::int[])`
    patterns on raw SQL.
- **Depends on**: Modules 2-7 (migrate writes first so any regression in
  write paths surfaces before SELECT plumbing changes compound the blast
  radius).

### Module 9: Remove dead helpers

- **Path**: `toolkit.py`
- **Responsibility**:
  - Confirm zero remaining call sites of `_nav_run_query`, `_nav_run_one`,
    `_nav_execute`, and `_nav_build_update` via `grep -n "_nav_"
    toolkit.py`.
  - Delete the four method bodies (lines ~157-180 and ~297-382).
  - Remove the accompanying docstring block at lines 149-155 that
    references the deleted helpers.
  - Run `pytest packages/ai-parrot-tools/tests/unit/` and ensure nothing
    imports them.
- **Depends on**: Modules 2-8 (every write and SELECT migrated).

### Module 10: Integration smoke test

- **Path**: `packages/ai-parrot-tools/tests/integration/test_navigator_toolkit_migration.py` (new)
- **Responsibility**:
  - Requires a reachable Postgres (pytest `skip` when `NAVIGATOR_DSN`
    env var is absent).
  - Drives `create_program → create_module → create_dashboard →
    create_widget → update_widget → clone_dashboard` end-to-end on a
    scratch program slug, asserting row counts in `auth.programs`,
    `auth.program_clients`, `auth.program_groups`, `navigator.modules`,
    `navigator.client_modules`, `navigator.modules_groups`,
    `navigator.dashboards`, `navigator.widgets`.
  - Verifies idempotency by calling `create_program` twice with the same
    slug and asserting `already_existed=True` on the second call and
    that no duplicate `program_clients` / `program_groups` rows are
    created.
  - Verifies transactional rollback by monkey-patching
    `PostgresToolkit.upsert_row` to raise after the first successful
    write inside `create_module`, then asserts the program still has no
    module row (rollback worked).
  - Tears down by deleting the scratch program + cascade.
- **Depends on**: Modules 1-9.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_get_tools_names_unchanged_post_migration` | 1 | `NavigatorToolkit.get_tools()` returns the same 28-tool list before and after every migration task |
| `test_get_tools_descriptions_unchanged_post_migration` | 1 | Tool descriptions (`tool.description`) remain byte-identical |
| `test_create_program_confirm_execution_false_returns_plan_dict` | 1 | `create_program(..., confirm_execution=False)` returns `{"status": "confirm_execution", …}` and performs zero DB calls |
| `test_create_module_confirm_execution_false_returns_plan_dict` | 1 | same for `create_module` |
| `test_create_dashboard_confirm_execution_false_returns_plan_dict` | 1 | same for `create_dashboard` |
| `test_create_widget_confirm_execution_false_returns_plan_dict` | 1 | same for `create_widget` |
| `test_clone_dashboard_confirm_execution_false_returns_plan_dict` | 1 | same for `clone_dashboard` |
| `test_create_program_uses_transaction` | 2 | Mocked `PostgresToolkit.transaction` is entered once per `create_program(confirm_execution=True)` call |
| `test_create_program_calls_upsert_row_for_program_clients` | 2 | First `upsert_row` call targets `auth.program_clients` with `conflict_cols=["program_id","client_id"]`, `update_cols=[]` |
| `test_create_program_calls_upsert_row_for_modules_groups` | 2 | `upsert_row` for `navigator.modules_groups` uses `update_cols=["active"]` |
| `test_create_program_idempotent_returns_existing_id` | 2 | Re-running with same `program_slug` returns `already_existed=True` with existing `program_id` |
| `test_create_program_gprogram_id_falls_back_to_execute_query` | 2 | `auth.program_groups` INSERT (with `SELECT MAX(gprogram_id)+1` sub-expression) is routed through `execute_query`, documented exception |
| `test_create_module_uses_transaction` | 3 | transaction wrapper entered |
| `test_create_module_home_slug_convention_preserved` | 3 | When `module_name.lower() == "home"`, `module_slug` and `classname` equal `program_slug` in the `insert_row` data dict |
| `test_create_module_prefix_rule_preserved` | 3 | For non-Home modules, `module_slug` is prefixed `{program_slug}_{slug}` unless already prefixed |
| `test_create_dashboard_insert_row_payload_shape` | 4 | `insert_row` called once with the 20-column data dict; JSON columns (`attributes`, `filtering_show`, `conditions`, `cond_definition`, `params`) are plain dicts (the dynamic Pydantic model handles encoding) |
| `test_clone_dashboard_atomic_rollback` | 5 | Simulated failure mid-fanout rolls back all widget writes |
| `test_create_widget_updates_parent_dashboard_attributes` | 6 | `update_row("navigator.dashboards", …)` called with merged `widget_location` inside same transaction as widget insert |
| `test_assign_module_to_client_upsert_semantics` | 7 | `conflict_cols=["client_id","program_id","module_id"]`, `update_cols=["active"]` |
| `test_assign_module_to_group_upsert_semantics` | 7 | `conflict_cols=["group_id","module_id","client_id","program_id"]`, `update_cols=["active"]` |
| `test_list_programs_uses_select_rows` | 8 | Mock asserts `select_rows` called; no raw SQL helper invoked |
| `test_list_modules_sort_by_newest_preserved` | 8 | `sort_by_newest=True` → `order_by=["inserted_at DESC"]` passed to `select_rows` |
| `test_get_full_program_structure_still_uses_execute_query` | 8 | Complex-JOIN method retains raw-SQL path as documented |
| `test_search_still_uses_execute_query` | 8 | UNION search retains raw-SQL path |
| `test_toolkit_has_no_nav_run_query` | 9 | `hasattr(NavigatorToolkit, "_nav_run_query") is False` |
| `test_toolkit_has_no_nav_run_one` | 9 | `hasattr(NavigatorToolkit, "_nav_run_one") is False` |
| `test_toolkit_has_no_nav_execute` | 9 | `hasattr(NavigatorToolkit, "_nav_execute") is False` |
| `test_toolkit_has_no_nav_build_update` | 9 | `hasattr(NavigatorToolkit, "_nav_build_update") is False` |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_program_module_dashboard_widget` | Full fan-out against a live PG, asserts expected row counts across 7 tables and idempotency on second run |
| `test_transaction_rollback_on_mid_flow_failure` | Monkey-patches `upsert_row` to raise on second call inside `create_module`; asserts no orphan row in `navigator.modules` |
| `test_confirm_execution_plan_then_confirm_materializes_rows` | Calls each `create_*` first with default (plan only, no rows), then with `confirm_execution=True`; asserts rows appear only after confirm |
| `test_update_dashboard_pk_enforcement_unchanged` | `update_dashboard(dashboard_id=uuid, …)` succeeds; a crafted no-WHERE SQL would fail (regression check inherited from FEAT-106) |

### Test Data / Fixtures

```python
# tests/unit/conftest.py (extend)
@pytest.fixture
def navigator_toolkit_factory(mocker):
    """Build a NavigatorToolkit with mocked PostgresToolkit CRUD methods.

    Returns (toolkit, mocks) where mocks has .insert_row, .upsert_row,
    .update_row, .select_rows, .execute_query, .transaction as AsyncMocks.
    """
    def _factory(user_id: int = 1, is_superuser: bool = True, **kwargs):
        tk = NavigatorToolkit(dsn="postgres://stub", user_id=user_id, **kwargs)
        # Avoid real connection warm-up
        tk._is_superuser = is_superuser
        tk._user_programs = set()
        tk._user_groups = {1}
        tk._user_clients = set()
        tk._user_modules = set()
        # Patch CRUD primitives
        for name in ("insert_row", "upsert_row", "update_row",
                    "delete_row", "select_rows", "execute_query"):
            setattr(tk, name, mocker.AsyncMock())
        tk.transaction = mocker.MagicMock(
            return_value=_AsyncContextManager(conn=mocker.AsyncMock())
        )
        return tk
    return _factory


@pytest.fixture
def navigator_dsn():
    """DSN for integration tests. Tests skip when unset."""
    dsn = os.environ.get("NAVIGATOR_DSN")
    if not dsn:
        pytest.skip("NAVIGATOR_DSN not set; integration tests skipped.")
    return dsn
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `grep -c "_nav_run_query\|_nav_run_one\|_nav_execute\|_nav_build_update" packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` returns **0** (all helpers removed).
- [ ] `grep -c "INSERT INTO\|UPDATE auth\.\|UPDATE navigator\." packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` returns **≤ 2** (the documented exceptions: `auth.program_groups` with `SELECT MAX(gprogram_id)+1` sub-expression, and the `setval(pg_get_serial_sequence(...))` sequence-repair call).
- [ ] `NavigatorToolkit.get_tools()` returns the same 28 tool names and identical descriptions as the pre-migration baseline captured in Module 1.
- [ ] Every `create_*`, `clone_*`, and `assign_*` method's
      `confirm_execution=False` branch returns `{"status": "confirm_execution", …}`
      without touching asyncdb (verified by `AsyncMock.call_count == 0`).
- [ ] `create_program`, `create_module`, `create_widget`, `clone_dashboard`
      each open exactly one `transaction()` per `confirm_execution=True` call.
- [ ] Simulated mid-flow failure in `create_module` rolls back the
      partially-written program (integration test).
- [ ] `create_program` idempotency re-run (`already_existed=True`) asserts no
      duplicate rows in `auth.program_clients`, `auth.program_groups`,
      `navigator.client_modules`, or `navigator.modules_groups`.
- [ ] Home-module slug convention and `{program_slug}_{slug}` prefix rule
      are preserved (unit-tested against the `insert_row` call data dict).
- [ ] `list_modules(sort_by_newest=True, limit=1)` returns the latest row
      ordered by `inserted_at DESC` (integration-tested).
- [ ] `get_full_program_structure`, `search`, `find_widget_templates`,
      `search_widget_docs`, `get_widget_schema`, and `list_widget_categories`
      keep using `self.execute_query(…)` as documented exceptions — no
      behavioural regression.
- [ ] Authorization guardrails (`_check_program_access`, `_check_module_access`,
      `_check_write_access`, `_require_superuser`, `_load_user_permissions`)
      remain byte-identical (verified by diffing with `git show
      HEAD~N:toolkit.py` at merge time).
- [ ] All new unit tests pass: `pytest packages/ai-parrot-tools/tests/unit/ -v`.
- [ ] Integration tests pass or are skip-marked cleanly when
      `NAVIGATOR_DSN` is unset: `pytest packages/ai-parrot-tools/tests/integration/ -v`.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/navigator/` reports zero new findings.
- [ ] `python -m py_compile packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` succeeds.
- [ ] No file outside
      `packages/ai-parrot-tools/src/parrot_tools/navigator/` and
      `packages/ai-parrot-tools/tests/` is modified (verified via
      `git diff --name-only HEAD..feat-107-navigator-toolkit-method-migration`).
- [ ] Downstream FEAT-106 tests remain green:
      `pytest packages/ai-parrot/tests/unit/test_postgres_toolkit.py -v`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.**
> Every reference below is verified against the repository state at
> `HEAD` on branch `dev`. Implementation agents MUST use these imports
> and signatures verbatim.

### Verified Imports

```python
# Confirmed via Read + Grep on 2026-04-17:

from parrot.bots.database.toolkits.postgres import PostgresToolkit
# verified at: packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:28

from parrot.tools.decorators import tool_schema
# used at: packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py:22

from .schemas import (
    ProgramCreateInput, ProgramUpdateInput,
    ModuleCreateInput, ModuleUpdateInput,
    DashboardCreateInput, DashboardUpdateInput,
    WidgetCreateInput, WidgetUpdateInput,
    CloneDashboardInput,
    AssignModuleClientInput, AssignModuleGroupInput,
    EntityLookupInput, SearchInput,
)
# verified at: packages/ai-parrot-tools/src/parrot_tools/navigator/schemas.py
```

### Existing Class Signatures (the CRUD surface this migration consumes)

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    async def insert_row(                                       # line 361
        self,
        table: str,
        data: Dict[str, Any],
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]: ...

    async def upsert_row(                                       # line 406
        self,
        table: str,
        data: Dict[str, Any],
        conflict_cols: Optional[List[str]] = None,
        update_cols: Optional[List[str]] = None,
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]: ...

    async def update_row(                                       # line 490
        self,
        table: str,
        data: Dict[str, Any],
        where: Dict[str, Any],
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]: ...

    async def delete_row(                                       # line 554
        self,
        table: str,
        where: Dict[str, Any],
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]: ...

    async def select_rows(                                      # line 609
        self,
        table: str,
        where: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
        order_by: Optional[List[str]] = None,
        limit: Optional[int] = None,
        conn: Optional[Any] = None,
    ) -> List[Dict[str, Any]]: ...

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]: ...      # line 697

    async def reload_metadata(                                  # line 737
        self, schema_name: str, table: str,
    ) -> None: ...
```

```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py (current)
class NavigatorToolkit(PostgresToolkit):
    tool_prefix: str = "nav"                                    # line 56

    _NAVIGATOR_TABLES: List[str] = [                            # lines 59-73
        "auth.programs", "auth.program_clients", "auth.program_groups",
        "auth.clients", "auth.groups", "auth.user_groups",
        "navigator.modules", "navigator.client_modules",
        "navigator.modules_groups",
        "navigator.dashboards", "navigator.widgets",
        "navigator.widgets_templates", "navigator.widget_types",
    ]

    def __init__(                                               # line 75
        self,
        dsn: str = "",
        default_client_id: int = 1,
        user_id: Optional[int] = None,
        confirm_execution: bool = False,
        page_index: Optional[Any] = None,
        builder_groups: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None: ...

    # TO BE REMOVED at end of migration (Module 9):
    async def _nav_run_query(self, sql, params=None) -> list: ...  # line 157
    async def _nav_run_one(self, sql, params=None) -> Optional[dict]: ...  # line 165
    async def _nav_execute(self, sql, params=None) -> Any: ...     # line 173
    async def _nav_build_update(                                   # line 297
        self, table, pk_col, pk_val, data,
        confirm_execution=False, include_updated_at=False,
    ) -> dict: ...

    # PRESERVED (authorization + business rules):
    async def _resolve_program_id(self, program_id=None, program_slug=None) -> int: ...  # line 211
    async def _resolve_module_id(self, ...) -> int: ...                                   # line 224
    async def _resolve_dashboard_id(self, ...) -> str: ...                                # line 243
    async def _resolve_client_ids(self, ...) -> List[int]: ...                            # line 263
    async def _load_user_permissions(self) -> None: ...                                   # line 397
    async def _check_program_access(self, program_id: int) -> None: ...                   # line 474
    async def _check_client_access(self, client_id: int) -> None: ...                     # line 489
    async def _check_module_access(self, ...) -> None: ...                                # line 505
    async def _check_dashboard_access(self, dashboard_id: str) -> None: ...               # line 540
    async def _check_widget_access(self, widget_id: str) -> None: ...                     # line 559
    async def _require_superuser(self) -> None: ...                                       # line 580
    async def _check_write_access(self, program_id: int) -> None: ...                     # line 593

    # PRESERVED (LLM-facing write tools, BODIES migrated):
    async def create_program(...) -> Dict[str, Any]: ...                                  # line 657
    async def update_program(self, program_id: int, **kwargs) -> Dict[str, Any]: ...      # line 793
    async def create_module(...) -> Dict[str, Any]: ...                                   # line 850
    async def update_module(self, module_id: int, **kwargs) -> Dict[str, Any]: ...        # line 1016
    async def create_dashboard(...) -> Dict[str, Any]: ...                                # line 1088
    async def update_dashboard(self, dashboard_id, confirm_execution=False, **kw): ...    # line 1184
    async def clone_dashboard(...) -> Dict[str, Any]: ...                                 # line 1244
    async def create_widget(...) -> Dict[str, Any]: ...                                   # line 1332
    async def update_widget(self, widget_id, confirm_execution=False, **kw): ...          # line 1440
    async def assign_module_to_client(...) -> Dict[str, Any]: ...                         # line 1536
    async def assign_module_to_group(...) -> Dict[str, Any]: ...                          # line 1551

    # PRESERVED (read tools — some bodies migrated to select_rows, others stay raw):
    async def get_program(...) -> Dict[str, Any]: ...                                     # line 804
    async def list_programs(...) -> Dict[str, Any]: ...                                   # line 824
    async def get_module(...) -> Dict[str, Any]: ...                                      # line 1030
    async def list_modules(...) -> Dict[str, Any]: ...                                    # line 1052
    async def get_dashboard(...) -> Dict[str, Any]: ...                                   # line 1197
    async def list_dashboards(...) -> Dict[str, Any]: ...                                 # line 1214
    async def get_widget(...) -> Dict[str, Any]: ...                                      # line 1481
    async def list_widgets(...) -> Dict[str, Any]: ...                                    # line 1503
    async def list_widget_types(self) -> Dict[str, Any]: ...                              # line 1569
    async def list_widget_categories(self) -> Dict[str, Any]: ...                         # line 1577
    async def list_clients(self, active_only=True, limit=500, **kw): ...                  # line 1585
    async def list_groups(...) -> Dict[str, Any]: ...                                     # line 1596
    async def get_widget_schema(self, widget_type_id: str): ...                           # line 1618  — raw SQL retained
    async def find_widget_templates(...) -> Dict[str, Any]: ...                           # line 1682  — raw SQL retained
    async def search_widget_docs(self, query: str): ...                                   # line 1715  — raw SQL retained
    async def get_full_program_structure(...) -> Dict[str, Any]: ...                      # line 1750  — raw SQL retained
    async def search(self, query, entity_type=None, limit=20): ...                        # line 1798  — raw SQL retained
```

### Integration Points

| New Call Site | Replaces | Via | Verified At |
|---|---|---|---|
| `create_program` body | `_nav_execute(INSERT auth.programs)` | `insert_row` | `toolkit.py:759` |
| `create_program` body | `_nav_execute(INSERT auth.program_clients ON CONFLICT)` | `upsert_row(update_cols=[])` | `toolkit.py:721,774` |
| `create_program` body | `_nav_execute(INSERT navigator.client_modules ON CONFLICT DO UPDATE)` | `upsert_row(update_cols=["active"])` | `toolkit.py:727` |
| `create_program` body | `_nav_execute(INSERT navigator.modules_groups ON CONFLICT DO UPDATE)` | `upsert_row(update_cols=["active"])` | `toolkit.py:742` |
| `create_module` body | same pattern, navigator.modules + cascades | `insert_row` + `upsert_row` | `toolkit.py:968,933,984` |
| `create_dashboard` body | `_nav_run_one(INSERT navigator.dashboards RETURNING)` | `insert_row(returning=[…])` | `toolkit.py:1157` |
| `create_widget` body | `_nav_run_one(INSERT navigator.widgets RETURNING)` + `_nav_execute(UPDATE navigator.dashboards)` | `insert_row` + `update_row` in `transaction()` | `toolkit.py:1389,1429` |
| `clone_dashboard` body | `_nav_run_one(INSERT …)` + fan-out loop | `insert_row` + loop of `insert_row(conn=tx)` | `toolkit.py:1282,1298` |
| `assign_module_to_client` / `_group` | `_nav_execute(INSERT … ON CONFLICT)` | `upsert_row(update_cols=["active"])` | `toolkit.py:1536,1551` |

### Does NOT Exist (Anti-Hallucination)

- ~~`PostgresToolkit.bulk_insert`~~ — not implemented; use a loop of
  `insert_row(conn=tx)` inside a `transaction()` instead.
- ~~`PostgresToolkit.execute_many`~~ — not a public method.
- ~~`select_rows(where={"col": {"op": "in", "value": [...]}})`~~ —
  `select_rows` takes equality-only `where`. For `ANY($1::int[])` or
  `IN (…)` patterns, fall back to `self.execute_query(sql, …)`.
- ~~`select_rows(where={"col": None})`~~ — `None` values are stripped by
  the dynamic Pydantic model's `exclude_none=True`. Use
  `execute_query` for `IS NULL` filters.
- ~~`upsert_row(conflict_cols="pk")`~~ — `conflict_cols` must be a list,
  even for a single-column target: `conflict_cols=["program_id"]`.
- ~~`transaction()` supports nested blocks~~ — it raises `RuntimeError`
  on nested entry (see `postgres.py:716-720`). Do not wrap
  `create_module` inside a caller that already opened a transaction.
- ~~`reload_metadata` is called automatically on schema change~~ — it is
  not; callers trigger it manually. Not relevant to this migration.
- ~~`NavigatorToolkit.page_index` drives query shape~~ — stored on
  `self._page_index` but not consulted by any CRUD call. Ignore.
- ~~`self._check_widget_access` accepts slug~~ — UUID only (toolkit.py:559).

### User-Provided Code

None. The brainstorm document
`Implementing AsyncPool Navigator Toolkit.md` (repo root, untracked,
1745 lines) is the conversational record of why each migration target
exists. It is narrative prose, not code, and is not required reading
for implementation.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **One method per task.** Do not batch multiple method rewrites in a
  single commit — it makes code review and bisect useless.
- **Tests first, then body.** For each method-level task:
  1. Write the unit test that asserts `confirm_execution=False` plan
     shape is unchanged (it will pass today — establishes baseline).
  2. Write the unit test asserting the NEW CRUD call shape (it will
     fail until the body is rewritten).
  3. Rewrite the body. Both tests pass.
- **Keep the `confirm_execution=False` branch first.** Build the plan
  dict before acquiring the transaction. The transaction must never
  surround the plan branch.
- **Thread `conn=tx` everywhere inside a transaction block.** Omitting
  it causes `PostgresToolkit` to acquire a fresh connection from the
  pool, breaking atomicity without raising.
- **Preserve exact dict shapes.** Return values
  (`{"status": "success", "result": {…}, "metadata": {…}}`) must stay
  identical — downstream agents parse them by key.
- **Dynamic Pydantic handles JSON.** Do not call `self._jsonb(value)`
  before passing to `insert_row` / `upsert_row` — the parent's
  `_prepare_args` + `_json_cols_for` reads `TableMetadata.columns` and
  emits `$N::text::jsonb` casts automatically. Pass plain dicts.
- **When in doubt, fall back to `execute_query`.** It's the documented
  escape hatch for anything `select_rows` / `upsert_row` can't express.
- **Follow the existing async / logger / type-hint conventions** from
  the rest of the file — no stylistic drift.

### Known Risks / Gotchas

- **Risk**: `upsert_row(update_cols=[])` semantic. In FEAT-106's
  implementation, an empty `update_cols` list means `DO NOTHING` (no
  SET clause emitted). Verify this is exactly the observed behaviour
  before relying on it in Module 2; if the implementation treats
  `update_cols=[]` differently, add `ON CONFLICT DO NOTHING` handling
  via a `conflict_action="nothing"` kwarg instead (to be added to
  `PostgresToolkit` if missing — flagged as open question Q1).
  **Mitigation**: A unit test in Module 1 pins the semantic by
  inspecting the SQL returned from `_get_or_build_template("upsert", …,
  update_cols=())` before any method is migrated.
- **Risk**: Warm metadata dependency. `_resolve_table` requires
  `self.cache_partition` to contain the table's `TableMetadata`, which
  is populated by `_warm_table_cache` on `start()`. If a
  `NavigatorToolkit` is constructed and a CRUD method is called before
  `start()` finishes, `_resolve_table` raises `ValueError`.
  **Mitigation**: Every existing test fixture that instantiates the
  toolkit already awaits `start()`; document in the new test fixture
  that the same contract is required.
- **Risk**: `create_program`'s `auth.program_groups` INSERT uses
  `SELECT COALESCE(MAX(gprogram_id), 0) + 1 FROM auth.program_groups`
  inline — a scalar subquery that `upsert_row.data` cannot express.
  **Mitigation**: Keep this INSERT on `self.execute_query(sql, …)` and
  document the exception in Module 2 and the Acceptance Criteria.
- **Risk**: Column-set drift. If the live schema has an additional
  column that the dynamic Pydantic model now requires (e.g., a new
  `NOT NULL` column with no default), the migration fails at
  `insert_row` with `pydantic.ValidationError`.
  **Mitigation**: Run the integration smoke test (Module 10) against
  staging before merging; document which schema columns are assumed
  nullable.
- **Risk**: Silent regression in list/search output shape. Agents
  downstream (navigator-agent-server) parse `list_modules` rows by
  key name. `select_rows` returns every column in the table (no SELECT
  list), which may introduce keys the agent has never seen.
  **Mitigation**: Pass an explicit `columns=[…]` to `select_rows` for
  every list tool, matching the pre-migration `SELECT col1, col2, …`
  list byte-for-byte.
- **Risk**: `list_modules` currently emits `inserted_at::text,
  updated_at::text` casts to force the LLM to see date strings.
  `select_rows` does not support per-column casts.
  **Mitigation**: Keep `list_modules` on `execute_query` until / unless
  `select_rows` gains a `column_casts=` kwarg. Flag as open question Q2.

### External Dependencies

No new external dependencies. Relies entirely on already-installed
FEAT-106 surface area.

---

## 8. Open Questions

> Must be resolved before or during implementation.

- [ ] **Q1** — Does `PostgresToolkit.upsert_row(update_cols=[])` produce
      `ON CONFLICT … DO NOTHING` or omit the entire `ON CONFLICT`
      clause? Check `_build_upsert_sql` in `postgres.py` / `_crud.py`.
      If neither matches, add a `conflict_action: Literal["nothing",
      "update"] = "update"` kwarg in FEAT-106 as a prerequisite.
      *Owner: Javier León*
- [ ] **Q2** — Does `select_rows` support per-column casts
      (`col::text`) for timestamp-to-string coercion needed by
      `list_modules`? If not, should `list_modules` stay on
      `execute_query` indefinitely, or should the SELECT list be
      augmented in FEAT-106? *Owner: Jesus Lara*
- [ ] **Q3** — Should the `setval(pg_get_serial_sequence(...))`
      sequence-repair call in `create_program` be kept (it's defensive
      against DBA manual inserts that skip the sequence) or removed?
      *Owner: Javier León*
- [ ] **Q4** — `list_widget_categories` uses `SELECT DISTINCT category
      FROM navigator.widget_types`. Is `DISTINCT` support worth adding
      to `select_rows`, or does this method stay on `execute_query`?
      *Owner: Jesus Lara*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — single worktree for all tasks.
- **Rationale**: Every task modifies the same file
  (`packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`).
  Parallel branches would produce constant merge conflicts; sequential
  execution in one worktree matches the file-locality of the work.
- **Task order**: Tasks run sequentially as Module 1 → Module 2 → …
  Module 10. Each task commits before the next begins, so each
  intermediate state is compilable and testable.
- **Cross-feature dependencies**: FEAT-106 must be merged to `dev`
  before starting (already merged: see commit
  `9fb3ea04 fix(feat-106): address all code-review findings before merge`).
- **Worktree creation** (after spec is approved and tasks decomposed):
  ```bash
  git checkout dev
  git worktree add -b feat-107-navigator-toolkit-method-migration \
    .claude/worktrees/feat-107-navigator-toolkit-method-migration HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-17 | Javier León | Initial draft — 10 modules, builds on FEAT-106 merged surface |
