---
type: Wiki Overview
title: 'Feature Specification: NavigatorToolkit Method Migration to PostgresToolkit
  CRUD'
id: doc:sdd-specs-navigator-toolkit-method-migration-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-106 refactored `NavigatorToolkit` to inherit from `PostgresToolkit`
  and
relates_to:
- concept: mod:parrot.bots.database.toolkits.postgres
  rel: mentions
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
---

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
- **G9** — Extend `PostgresToolkit.select_rows` with two additive,
  backwards-compatible parameters: `distinct: bool = False` and
  `column_casts: Optional[Dict[str, str]] = None`. Required by
  `list_modules` (timestamp-to-text coercion) and
  `list_widget_categories` (`SELECT DISTINCT category`). See Q2 / Q4
  resolutions in §8.
- **G10** — `upsert_row` is reserved for **true UPSERTs** (`DO UPDATE
  SET …`). `INSERT … ON CONFLICT DO NOTHING` semantics stay on
  `execute_query` with the explicit SQL string — avoids accidental
  overwrite if `update_cols=[]` ever silently changes meaning. See Q1
  resolution in §8.

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
  `nav_*` tools are introduced. (The additive `distinct` /
  `column_casts` parameters on `select_rows` live on `PostgresToolkit`,
  not the Navigator tool surface.)
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

### Module 0a: `PostgresToolkit.select_rows` — add `distinct` + `column_casts`

- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py`
  (method at line 609) + `packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py`
  (`_build_select_sql` signature).
- **Responsibility**:
  - Extend `select_rows` signature additively:
    ```python
    async def select_rows(
        self,
        table: str,
        where: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
        order_by: Optional[List[str]] = None,
        limit: Optional[int] = None,
        distinct: bool = False,                                # NEW (Q4)
        column_casts: Optional[Dict[str, str]] = None,         # NEW (Q2)
        conn: Optional[Any] = None,
    ) -> List[Dict[str, Any]]: ...
    ```
  - `distinct=True` → emit `SELECT DISTINCT` instead of `SELECT`.
  - `column_casts={"col": "text"}` → emit `col::text AS col` in the SELECT
    list for named columns. Cast type string is validated against a
    whitelist: `{"text", "uuid", "json", "jsonb", "integer", "bigint",
    "numeric", "timestamp", "date"}` — anything else raises
    `ValueError("unsupported cast type: ...")`. The whitelist lives in
    `_crud.py` next to `_build_select_sql`.
  - `_build_select_sql` in `_crud.py` grows matching parameters. When
    `columns` is `None` and `column_casts` names a column, expand
    `columns` to an explicit list covering all `TableMetadata.columns`
    so the cast can be applied to the right position. When `columns` is
    explicit, every `column_casts` key MUST appear in `columns` — else
    `ValueError`.
  - Update `_get_or_build_template` cache key to include `distinct` and
    a deterministic hash of `column_casts` (sorted `(col, cast)` tuple),
    so templates don't collide.
  - Backwards compatibility: both parameters default to their no-op
    values; existing callers behave byte-identically.
- **Tests** (extend `tests/unit/test_postgres_toolkit.py` and/or
  `test_crud_helpers.py`):
  - `test_select_rows_distinct_emits_select_distinct` — SQL contains
    `SELECT DISTINCT `.
  - `test_select_rows_column_casts_emits_cast_in_select_list` — `col::text`
    appears in generated SQL.
  - `test_select_rows_column_casts_rejects_unknown_type` — non-whitelisted
    cast raises `ValueError`.
  - `test_select_rows_column_casts_rejects_unknown_column` — cast key not
    in `columns` raises `ValueError`.
  - `test_select_rows_no_new_params_backcompat_identical_sql` — omitting
    both params produces the same SQL as before the extension.
  - `test_prepared_cache_key_changes_when_distinct_toggled` — cache is
    not shared between `distinct=True` and `distinct=False` for the
    same table.
- **Depends on**: nothing. Lands before any NavigatorToolkit work.
- **Note on package scope**: This module modifies
  `packages/ai-parrot/**` (not `ai-parrot-tools/`). Acceptance Criteria
  below is adjusted to scope cross-package changes to exactly this
  module.

### Module 1: Baseline regression tests (must land after 0a)

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
  - `INSERT INTO auth.program_clients … ON CONFLICT DO NOTHING`
    (lines 720-724, 773-777) **stays on `self.execute_query(sql, …, conn=tx)`**
    with the explicit `DO NOTHING` clause (per Q1 resolution — reserves
    `upsert_row` for intentional UPSERTs only).
  - Replace `INSERT INTO navigator.client_modules … ON CONFLICT … DO UPDATE
    SET active = EXCLUDED.active` (lines 726-730) with
    `self.upsert_row(..., conflict_cols=["client_id","program_id","module_id"],
    update_cols=["active"], conn=tx)`.
  - `INSERT INTO auth.program_groups ((SELECT COALESCE(MAX(...))+1 FROM
    auth.program_groups), $1, $2, $3, now()) ON CONFLICT DO NOTHING`
    (lines 733-738, 779-784) **stays on `self.execute_query(sql, …, conn=tx)`**
    for two reasons: (1) the `gprogram_id` scalar-subquery cannot be
    expressed via `upsert_row.data`, and (2) the `DO NOTHING`
    semantic is explicit per Q1 resolution.
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
  - Convert idempotency lookup (line 924) and existing-assignments to
    either `upsert_row` (when semantic is `DO UPDATE SET active = EXCLUDED.active`
    — `navigator.client_modules`, `navigator.modules_groups`) or
    `execute_query` (when semantic is `DO NOTHING` —
    `auth.program_clients`, `auth.program_groups`). Thread `conn=tx`
    through both paths (lines 933-952, 984-1003).
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
  - Both methods already use `ON CONFLICT … DO UPDATE SET active =
    EXCLUDED.active` — true UPSERT semantics. Convert each to
    `self.upsert_row(...)` with the correct `conflict_cols` and
    `update_cols=["active"]` (consistent with Q1: `upsert_row` is only
    for intentional `DO UPDATE`).

…(truncated)…
