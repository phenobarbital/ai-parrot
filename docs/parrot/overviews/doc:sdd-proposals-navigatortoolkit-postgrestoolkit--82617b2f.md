---
type: Wiki Overview
title: 'Brainstorm: NavigatorToolkit ↔ PostgresToolkit Interaction'
id: doc:sdd-proposals-navigatortoolkit-postgrestoolkit-interaction-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 1782 lines) is the LLM-facing toolkit for creating/updating Navigator entities
relates_to:
- concept: mod:parrot.bots.database
  rel: mentions
- concept: mod:parrot.bots.database.cache
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.base
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.postgres
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.sql
  rel: mentions
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.security.query_validator
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.database
  rel: mentions
- concept: mod:parrot.tools.databasequery
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
---

# Brainstorm: NavigatorToolkit ↔ PostgresToolkit Interaction

**Date**: 2026-04-17
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

`NavigatorToolkit` (`packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`,
1782 lines) is the LLM-facing toolkit for creating/updating Navigator entities
(Programs, Modules, Dashboards, Widgets, permissions). Every write path is a
hand-crafted `INSERT INTO … RETURNING …` string, with a separate `_build_update`
helper that concatenates `SET col = $N` fragments. This has three concrete
problems:

1. **No UPSERT / no ON CONFLICT control.** The current code has scattered
   `ON CONFLICT DO NOTHING` or `ON CONFLICT (…) DO UPDATE SET active = EXCLUDED.active`
   fragments duplicated across `create_program` / `create_module` (toolkit.py
   lines 654–679, 865–890, 918–941). Real UPSERTs with `SET col1 = EXCLUDED.col1, …`
   per table are not supported.
2. **Input validation is decoupled from database shape.** Pydantic input schemas
   (`schemas.py`) are hand-written and drift from the actual column set; nothing
   stops a caller from passing a field that was renamed in the DB. Column-level
   safety is all manual.
3. **Safety policy is duplicated.** The existing `SQLToolkit` / `PostgresToolkit`
   machinery already has metadata warm-up, `QueryValidator.validate_sql_ast`
   read-only / DML-with-WHERE enforcement, and a per-partition metadata cache —
   but `NavigatorToolkit` uses none of it. It opens its own `AsyncPool` via
   `asyncdb.AsyncPool("pg", params=…)` and builds SQL by hand.

Beyond `NavigatorToolkit`, there is no reusable CRUD surface on `PostgresToolkit`
itself: agents that need to write rows (FormBuilder, ComplianceReport, future
Navigator-adjacent toolkits) each re-invent the same INSERT/UPSERT string
assembly.

**Affected users:**
- End-users of Navigator AI agents — indirectly: failed UPSERTs today surface as
  duplicate-key errors rather than clean updates.
- Agent/toolkit developers — who want a uniform, safe write path without
  reinventing it per toolkit.

---

## Constraints & Requirements

- **C1 — Preserve tool surface.** `NavigatorToolkit.create_program` /
  `create_module` / `create_dashboard` / `create_widget` / `update_*` / `assign_*`
  must keep the same tool names and schemas (`schemas.py` stays the public
  contract to the LLM). Internal refactor only.
- **C2 — Cross-package dependency is already in place.**
  `packages/ai-parrot-tools/pyproject.toml` declares `ai-parrot>=0.24.27`, so
  `from parrot.bots.database.toolkits.postgres import PostgresToolkit` is a
  legal import from `NavigatorToolkit` (confirmed during Round 2 research).
- **C3 — Breaking constructor change is accepted** (per user Q6 answer, option b).
  `NavigatorToolkit(connection_params=…)` → `NavigatorToolkit(dsn=…)`. The
  example at `examples/navigator_agent.py` and `ai-parrot-tools` registry entries
  are updated in the same PR.
- **C4 — Transactional grouping and `RETURNING` must survive** (Round 1 Q2).
  Today `create_program` is effectively a multi-statement flow (`auth.programs`
  + N×`auth.program_clients` + N×`auth.program_groups` + N×N×`navigator.modules_groups`).
  The new CRUD layer must expose a transactional `async with` context to group
  these under a single PG connection / transaction.
- **C5 — Whitelist tables only.** The refactored toolkit's generic CRUD methods
  must reject operations on tables not in `self.tables`. Today `PostgresToolkit`
  has no such enforcement (confirmed Round 1 Q5) — this is a NEW guardrail the
  toolkit introduces alongside its CRUD surface.
- **C6 — PK-presence in WHERE for UPDATE/DELETE** (Round 1 Q5, Q10-a).
  `QueryValidator.validate_sql_ast` is extended with optional
  `require_pk_in_where` + `primary_keys` parameters, platform-wide.
- **C7 — Dynamic Pydantic validation** (Q8-i). Column name & `data_type` from
  `TableMetadata` drive a per-table Pydantic model via `pydantic.create_model`,
  reusing the PG→Python map at `datamodel.types.MODEL_TYPES` (already an
  installed transitive dependency; used by asyncdb's own `Model.makeModel`).
- **C8 — Prepared-statement cache scope** (Q4).
  Per-toolkit-instance private `dict`, keyed `f"{op}_{schema}_{table}"` (plus a
  hash of `conflict_cols` for UPSERT templates), no persistence, manual reload
  via `await toolkit.reload_metadata(schema, table)`.
- **C9 — No breakage of in-flight FEAT-105.** FEAT-105 renames
  `parrot.tools.database.DatabaseToolkit` → `DatabaseQueryToolkit`; that's a
  different module tree (`parrot.tools.*`, not `parrot.bots.database.*`). The
  classes we touch here — `SQLToolkit` / `PostgresToolkit` / `QueryValidator`,
  plus `NavigatorToolkit` in the other package — do not overlap with FEAT-105's
  file set.

---

## Options Explored

### Option A: Thin extension — private CRUD inside NavigatorToolkit

Make `NavigatorToolkit` subclass `PostgresToolkit` purely to reuse the metadata
cache + connection lifecycle + `QueryValidator`-gated `execute_query`. Keep all
INSERT/UPSERT/UPDATE template construction and Pydantic validation **private**
to `NavigatorToolkit` (e.g. in a `_model_cache` + `_prepared_cache` pair). The
generic `insert_row / upsert_row / …` shape stays internal — not exposed as
LLM tools, not reusable by other toolkits.

✅ **Pros:**
- Smallest refactor. ~1 week of work.
- Zero API change to other toolkits.
- Low risk of regressions outside Navigator.
- No new tools mean no new permission / collision surface to audit.

❌ **Cons:**
- Same CRUD machinery will be re-implemented in the next agent that needs it
  (FormBuilder, ComplianceReport).
- `PostgresToolkit` stays read-only from the LLM's perspective; generic write
  capabilities remain stuck inside bespoke agents.
- Doesn't address the "no UPSERT on generic PostgresToolkit" gap that will be
  hit the next time a database-writing agent is built.
- Pydantic-from-metadata generator is locked inside `NavigatorToolkit`, hard to
  reuse even internally.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Dynamic `create_model` for per-table input validation | already 2.12.5 |
| `sqlglot` | Reused via existing `QueryValidator` | already installed |
| `asyncdb` | Existing connection backend | already used by `SQLToolkit._execute_asyncdb` |
| `datamodel.types.MODEL_TYPES` | PG type → Python type map (24 entries) | installed via asyncdb transitively |

🔗 **Existing Code to Reuse:**
- `parrot.bots.database.toolkits.postgres.PostgresToolkit` — inherit for metadata cache, `start()`, `execute_query`.
- `parrot.bots.database.toolkits.sql.SQLToolkit._get_primary_keys_query` — PK extraction.
- `parrot.bots.database.cache.CachePartition.get_table_metadata` — returns `TableMetadata`.
- `parrot.security.QueryValidator.validate_sql_ast` — existing DDL + missing-WHERE guard.
- `parrot_tools/navigator/schemas.py` — Pydantic input schemas stay unchanged (LLM contract).

---

### Option B: Lift generic CRUD into PostgresToolkit (recommended)

Add first-class `insert_row / upsert_row / update_row / delete_row / select_rows`
methods to `PostgresToolkit` as public async tools (auto-discovered by
`AbstractToolkit._generate_tools()`). Each method:

1. Looks up `TableMetadata` from `cache_partition` (warmed via `tables=`).
2. Rejects tables not in `self.tables` (new whitelist enforcement).
3. Lazily builds a Pydantic model for the table using
   `pydantic.create_model(…)` with field types mapped from
   `datamodel.types.MODEL_TYPES`. Cached in `self._model_cache`.
4. Lazily builds the SQL template, cached in `self._prepared_cache` under
   `f"{op}_{schema}_{table}[_{conflict_hash}]"`.
5. Runs the SQL with positional params via `conn.execute(sql, *values)` (or
   `conn.fetchrow` when `RETURNING` is requested).

`NavigatorToolkit` becomes a `PostgresToolkit` subclass that:

- Passes `tables=[…]`, `allowed_schemas=["public","auth","navigator"]`,
  `primary_schema="navigator"`, `read_only=False`.
- Keeps `schemas.py` Pydantic inputs as the LLM contract.
- Keeps all authorization guardrails (`_check_program_access`,
  `_check_write_access`, `_require_superuser`, `_load_user_permissions`).
- Refactors each `create_*` / `update_*` / `assign_*` method to call
  `await self.upsert_row("auth.programs", data, conflict_cols=["program_slug"], returning=["program_id","program_slug"])`
  instead of hand-rolling SQL.
- Removes `connection_params` / `_get_db` / `_connection` / `_query` /
  `_query_one` / `_exec` / `_build_update` — these move into `PostgresToolkit`
  or are dropped.

**Write-tool visibility gating.** Under `read_only=True` (the default), the
new CRUD methods are added to `exclude_tools` so they never surface as LLM
tools on a read-only `PostgresToolkit` (e.g. a BI query agent). Under
`read_only=False` they're exposed.

**Extensions required in dependencies:**

- `QueryValidator.validate_sql_ast(…, require_pk_in_where=False, primary_keys=None)`
  parses the AST `where` expression, walks `exp.Column` nodes, and confirms at
  least one PK column is present on UPDATE/DELETE when the flag is on.
- `TableMetadata` gains `unique_constraints: List[List[str]]` — each entry is a
  list of column names forming a UNIQUE index (for UPSERT default conflict
  targets when PK isn't the right key, e.g. `(group_id, module_id, client_id, program_id)`
  on `navigator.modules_groups`).
- New hook `SQLToolkit._get_unique_constraints_query(schema, table)` —
  queries `information_schema.table_constraints` + `key_column_usage` for
  `UNIQUE` rows; `_build_table_metadata` populates the new field.
- New `_warm_prepared_cache()` is NOT added — templates build lazily; reload is
  manual via `await toolkit.reload_metadata(schema, table)` (drops and
  re-warms that entry).

**Transaction grouping** (C4): a new async context manager
`PostgresToolkit.transaction()` yields a connection that each CRUD helper
accepts via a `conn=` kwarg. `NavigatorToolkit.create_program` wraps its multi-
table flow in `async with self.transaction() as tx: await self.upsert_row(..., conn=tx)`.

✅ **Pros:**
- One canonical write path, reusable by every future PG agent.
- `TableMetadata` becomes a strictly richer primitive (+ unique constraints),
  useful beyond this feature.
- Prepared-statement cache is per-instance but the *design pattern* is
  documented once in `PostgresToolkit`.
- Platform-wide hardening: `require_pk_in_where` is available to any caller
  that opts in.
- Navigator's `_build_update` duplication disappears.
- Agent-facing tool surface on `PostgresToolkit` gains CRUD capabilities that
  FEAT-105's `DatabaseQueryToolkit` (renamed clone) pointedly does not —
  good separation of concerns (FEAT-105 is read-only query executor; this is
  table-scoped CRUD).

❌ **Cons:**
- Touches three files outside Navigator: `sql.py`, `postgres.py`,
  `query_validator.py` — needs tests in `tests/unit/test_postgres_toolkit.py`
  and potentially new tests for the validator extension.
- `PostgresToolkit` public tool surface grows → agents that import
  `PostgresToolkit(read_only=False)` get five new tools automatically. We
  mitigate with the `read_only` visibility gate.
- The write tools expose names like `insert_row` / `upsert_row` — without the
  `pg_` prefix they could collide with other toolkit methods. Need to confirm
  `tool_prefix` handling (`DatabaseToolkit.tool_prefix = "db"` → tools become
  `db_insert_row` etc., which is fine).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic>=2.12` | `create_model` for dynamic per-table validators | installed |
| `sqlglot` | `exp.Column` traversal for `require_pk_in_where` | already used by `QueryValidator` |
| `asyncdb>=2.15` | `conn.execute(sql, *params)` + `conn.fetchrow` / `conn.fetch` | installed |
| `datamodel.types.MODEL_TYPES` | PG type → Python type (shared with asyncdb Model path) | already transitive dep |

🔗 **Existing Code to Reuse:**
- `parrot.bots.database.toolkits.postgres.PostgresToolkit` (113 lines) — subclass + extend.
- `parrot.bots.database.toolkits.sql.SQLToolkit._build_table_metadata` (lines 545-595) — extend to include unique constraints.
- `parrot.bots.database.toolkits.sql.SQLToolkit._get_primary_keys_query` / `_get_columns_query` (lines 413-437) — already correct.
- `parrot.bots.database.toolkits.base.DatabaseToolkit._validate_identifier` (line 168) — reuse for safe `"schema"."table"` quoting.
- `parrot.bots.database.cache.CachePartition.get_table_metadata` / `.store_table_metadata` — no changes.
- `parrot.security.QueryValidator.validate_sql_ast` — extend with two kwargs.
- `parrot_tools/navigator/schemas.py` — unchanged (LLM input contract).

---

### Option C: asyncdb Model as canonical CRUD path (less-conventional)

Use `asyncdb.models.Model.makeModel(name, schema, fields=None, db=conn)` to
generate a dataclass per whitelisted table, then use its built-in `.insert()`
/ `.save()` / `.update()` / `.delete()` / `.filter()` methods for CRUD. No
hand-rolled SQL templates at all — asyncdb generates the SQL internally, and
asyncpg's native prepared-statement cache (one per connection, managed by the
driver) handles the performance side.

The pipeline is:
```
raw input dict → Pydantic schema (LLM contract) → asyncdb Model instance → Model.save()
```

✅ **Pros:**
- Zero template-management code in our codebase. asyncdb already knows how
  to generate INSERT/UPDATE/DELETE for a `Model`.
- Uses a well-tested library path.
- asyncpg's connection-level prepared-statement cache is automatic.

❌ **Cons:**
- **`ON CONFLICT (…) DO UPDATE SET col = EXCLUDED.col, …` is not a first-class
  feature of asyncdb Model.** The current Navigator INSERTs use:
  - `ON CONFLICT DO NOTHING`
  - `ON CONFLICT (group_id, module_id, client_id, program_id) DO UPDATE SET active = EXCLUDED.active`
  - `ON CONFLICT (client_id, program_id, module_id) DO UPDATE SET active = EXCLUDED.active`
  Replicating those precisely with `Model.save()` is either impossible or
  requires dropping back to raw SQL anyway — defeating the purpose.
- `RETURNING program_id, program_slug` on INSERT is model-specific plumbing in
  asyncdb; some versions return the `Model` instance, others a dict — the
  current Navigator code relies on deterministic `RETURNING` columns.
- Locks the platform into asyncdb's Model semantics; harder to swap out later.
- Still need a separate Pydantic validation layer for the LLM-facing tool
  inputs (asyncdb dataclasses are not Pydantic, so we'd carry both anyway).

📊 **Effort:** Medium (deceptively — the "asyncdb handles it" pitch breaks as
soon as real UPSERTs are required).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb>=2.15` | `Model.makeModel`, `.insert`, `.save`, `.update`, `.delete` | installed |
| `pydantic` | LLM-facing input validation (parallel to asyncdb Model) | installed |

🔗 **Existing Code to Reuse:**
- `asyncdb.models.Model.makeModel` (confirmed signature during research).
- `parrot.bots.database.toolkits.postgres.PostgresToolkit` — inherit for connection lifecycle only.

---

## Recommendation

**Option B** is recommended.

The user's Q7-a answer (generic CRUD on `PostgresToolkit`) and Q8-i answer
(prepared-statement-cache with dynamic Pydantic validation) are the deciding
constraints. Option A would violate Q7-a by keeping the machinery private to
Navigator; Option C would violate Q8-i by hiding SQL behind asyncdb Model's
black-box generation and — more critically — cannot express the heterogeneous
`ON CONFLICT` targets the Navigator tables actually use (`(program_slug)` for
programs, `(client_id, program_id, module_id)` for client_modules,
`(group_id, module_id, client_id, program_id)` for modules_groups). The exact
UPSERT semantics are the current pain point; a solution that fakes them
indirectly is no solution.

The tradeoff we're accepting:
- We own more code (template builder, pydantic generator, visibility gating)
  than Option C, in exchange for **exact control** over `ON CONFLICT`,
  `RETURNING`, and per-table-unique-constraint discovery — the very features
  that the current hand-written SQL exists to express.
- We ship more surface area than Option A (three packages touched vs one), in
  exchange for a reusable generic CRUD layer that removes the next
  "I need to write to Postgres from an agent" reinvention.

---

## Feature Description

### User-Facing Behavior

From the LLM's perspective, the observable behaviour is **unchanged**:

- `create_program` / `update_program` / `create_module` / `create_dashboard` /
  `create_widget` / `update_*` / `assign_*` / `list_*` / `search` / `get_full_program_structure`
  tools keep the same names, schemas, and `confirm_execution` / `dry_run`
  guardrails.
- Responses keep the same `{"status": "success" | "confirm_execution" | "error",
  "result": …, "metadata": …}` shape.
- The `PLAN GENERADO` preview on unconfirmed calls still exposes the eventual
  SQL (now taken from the prepared-statement cache template rather than built
  inline).

From the **PostgresToolkit-as-platform** perspective, new agents built with
`PostgresToolkit(dsn=…, read_only=False, tables=[…])` get five additional
LLM-callable tools out of the box: `db_insert_row`, `db_upsert_row`,
`db_update_row`, `db_delete_row`, `db_select_rows` (prefixed via the existing
`tool_prefix = "db"` convention).

### Internal Behavior

1. **Startup.**
   `PostgresToolkit.start()` (inherited) connects; `_warm_table_cache()`
   (SQLToolkit, existing) populates `cache_partition` with `TableMetadata` —
   *extended* in this feature to also populate `unique_constraints` by
   running the new `_get_unique_constraints_query(schema, table)`.

2. **First write of the session.**
   `upsert_row("auth.programs", data, conflict_cols=["program_slug"],
   returning=["program_id","program_slug"])` flows:
   - Whitelist check: `"auth.programs" in self.tables`? → else `ValueError`.
   - Metadata lookup: `meta = await self.cache_partition.get_table_metadata("auth", "programs")`.
   - Pydantic model: `M = self._get_or_build_pydantic_model(meta)`.
     First call: uses `pydantic.create_model("AuthProgramsInput",
     **{col["name"]: (Optional[MODEL_TYPES[col["type"]]], Field(default=None))})`
     plus `field_validator` hooks for json/jsonb columns. Result is memoized via
     a `functools.lru_cache`-decorated module-level builder
     `_build_pydantic_model(model_name: str, columns_key: tuple[tuple[str, type, bool], ...]) -> Type[BaseModel]`
     — see the "Caching strategy for dynamic Pydantic models" subsection below.
   - Validated payload: `validated = M(**data).model_dump(exclude_none=True)`.
   - Template lookup / build: cache key
     `f"upsert_auth_programs_{hash(('program_slug',))}"`.
     First call: builds
     `INSERT INTO "auth"."programs" (c1,c2,…) VALUES ($1,$2,…)
      ON CONFLICT (program_slug) DO UPDATE SET c1=EXCLUDED.c1, c2=EXCLUDED.c2, …
      RETURNING program_id, program_slug`.
     Cached in `self._prepared_cache`.
   - Execute: `await conn.fetchrow(template, *values)` (asyncpg auto-caches at
     the connection layer for free).
   - Returns a dict shaped by `RETURNING`.

3. **UPDATE / DELETE safety path.**
   `update_row("navigator.dashboards", data, where={"dashboard_id": …})` → the
   builder emits `UPDATE … SET … WHERE dashboard_id = $N`, then runs it
   through `QueryValidator.validate_sql_ast(sql, dialect="postgres",
   read_only=False, require_pk_in_where=True,
   primary_keys=meta.primary_keys)` before executing. UPDATE/DELETE with a
   WHERE that doesn't mention a PK column is rejected platform-wide when the
   flag is on; CRUD helpers default it to `True`, raw `execute_query` leaves
   it `False` for caller flexibility.

4. **Transactional grouping (C4).**
   `async with self.transaction() as tx:` yields a pooled connection within a
   transaction; every CRUD helper accepts `conn=tx` and skips
   acquire/release. Context-manager exit commits or rolls back.

5. **Whitelist rejection.**
   CRUD helpers raise `ValueError(f"Table {schema}.{table} not in allowed
   tables")` before any SQL is built. Raw `execute_query` is unchanged —
   it can still reach tables outside `tables` but remains gated by
   `QueryValidator`.

6. **Reload.**
   `await toolkit.reload_metadata("navigator", "widgets")` purges the entry in
   `self.cache_partition` (per-table), calls `_build_pydantic_model.cache_clear()`
   (blast-radius note below), and removes entries in `self._prepared_cache`
   that reference that table; next access re-warms from the database.

#### Caching strategy for dynamic Pydantic models

Three viable patterns were considered:

| Pattern | Pros | Cons |
|---|---|---|
| Plain `self._model_cache: dict[str, type[BaseModel]]` | Per-instance, granular invalidation per table, no extra deps | Not size-capped; slightly less idiomatic |
| `@functools.lru_cache` on **module-level** `_build_pydantic_model(model_name, columns_key_tuple)` where `columns_key_tuple` is a hashable representation of `TableMetadata.columns` | Idiomatic, auto size-capped, `cache_info()` for observability, same identical-schema-shape yields same class across toolkit instances (memory win) | `cache_clear()` wipes **all** entries — per-table reload requires rebuilding others on next access |
| `@functools.lru_cache` directly on a `self`-bound method | Simple syntax | `self` lives in cache key → retains a reference to the instance → per-instance cache pollution / memory-leak smell |

**Recommended**: pattern 2 — `functools.lru_cache(maxsize=256)` on a
module-level helper. Rationale: `create_model` is deterministic given
`(model_name, tuple((col_name, py_type, nullable) for col in columns))`, so
two `PostgresToolkit` instances pointed at the same DB share the same model
class — memory stays flat as agents spin up. The `cache_clear()` blast
radius on reload is acceptable because reloads are rare (manual operator
action, per C8) and the rebuild cost is microseconds per table.

The SQL **template** cache (`self._prepared_cache`) remains a plain
per-instance `dict`, since templates depend on runtime-provided
`conflict_cols` and `returning` parameters that aren't easy to hash into a
globally-shared cache without key explosion; plus per-table eviction on
`reload_metadata` is clean.

### Edge Cases & Error Handling

- **Metadata missing.** If a CRUD helper is called for a table not warmed
  (wasn't in `tables=[…]` at start), raise `ValueError`, don't silently warm
  on-demand — warming requires the connection, and surprise DDL-class queries
  at LLM-call time defeat the "prepared at warm-up" story.
- **Column mismatch.** Pydantic validation rejects unknown fields with
  `extra="forbid"` (configured at `create_model` time) → the caller sees a
  structured pydantic `ValidationError`, not a late PG error.
- **Composite PK, nullable column in PK, partial WHERE.**
  `require_pk_in_where` is satisfied by *any* PK column appearing in WHERE;
  we don't require *all* PK columns. This matches typical update-by-id flows
  but leaves the caller responsible for specificity. Documented.
- **UPSERT conflict target not UNIQUE.** PG errors out at execute time; we
  don't attempt to validate conflict_cols against indexes. `TableMetadata.
  unique_constraints` is an advisory convenience for defaults, not a compile-
  time check.
- **`jsonb` and `jsonb[]` columns.** Pydantic field type is `dict` / `list`;
  the template emits `$N::text::jsonb` for these columns (matching the
  current Navigator pattern). The generator identifies them by
  `col["type"] in {"json","jsonb","hstore"}`.
- **RETURNING requested on a table without the column.** Caller error;
  propagate PG's `UndefinedColumn` as-is.
- **Primary key not in data on INSERT.** Works for serial / uuid-default PKs
  — omitted columns don't appear in the INSERT column list; PG applies the
  default. Explicit PK values override.

…(truncated)…
