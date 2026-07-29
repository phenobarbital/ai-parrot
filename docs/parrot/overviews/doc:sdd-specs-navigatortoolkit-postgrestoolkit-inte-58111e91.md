---
type: Wiki Overview
title: 'Feature Specification: NavigatorToolkit ↔ PostgresToolkit Interaction'
id: doc:sdd-specs-navigatortoolkit-postgrestoolkit-interaction-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 1782 lines) is the LLM-facing toolkit for creating and updating Navigator
relates_to:
- concept: mod:parrot.bots.database
  rel: mentions
- concept: mod:parrot.bots.database.cache
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits
  rel: mentions
- concept: mod:parrot.bots.database.toolkits._crud
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
- concept: mod:parrot_tools.navigator
  rel: mentions
- concept: mod:parrot_tools.navigator.schemas
  rel: mentions
---

# Feature Specification: NavigatorToolkit ↔ PostgresToolkit Interaction

**Feature ID**: FEAT-106
**Date**: 2026-04-17
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

**Prior exploration**: [`sdd/proposals/navigatortoolkit-postgrestoolkit-interaction.brainstorm.md`](../proposals/navigatortoolkit-postgrestoolkit-interaction.brainstorm.md) (Recommended: Option B)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`NavigatorToolkit` (`packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`,
1782 lines) is the LLM-facing toolkit for creating and updating Navigator
entities (Programs, Modules, Dashboards, Widgets, permissions). Every write
path today is a hand-crafted `INSERT INTO … RETURNING …` string, with a
separate `_build_update` helper that concatenates `SET col = $N` fragments.
This produces three concrete problems:

1. **No first-class UPSERT / `ON CONFLICT` control.** The current code has
   scattered `ON CONFLICT DO NOTHING` or
   `ON CONFLICT (group_id, module_id, client_id, program_id) DO UPDATE SET active = EXCLUDED.active`
   fragments duplicated across `create_program`, `create_module`, and the
   idempotent branches (toolkit.py lines 654–679, 865–890, 918–941). Real
   UPSERTs with arbitrary conflict targets and `SET col = EXCLUDED.col` per
   column are not supported as a reusable primitive.
2. **Input validation is decoupled from database shape.** The Pydantic input
   schemas in `navigator/schemas.py` are hand-written and drift from the
   actual table columns; a renamed DB column is caught only at SQL execute
   time.
3. **Safety policy is duplicated.** `SQLToolkit` / `PostgresToolkit` already
   offers: metadata warm-up, `QueryValidator.validate_sql_ast` DDL +
   `read_only` + missing-WHERE enforcement, and a `CachePartition` metadata
   cache. `NavigatorToolkit` uses none of it — it opens its own
   `asyncdb.AsyncPool("pg", params=…)` and writes raw SQL.

Beyond Navigator, there is no reusable CRUD surface on `PostgresToolkit`
itself: every future agent that needs to write rows (FormBuilder,
ComplianceReport, etc.) will re-invent the same INSERT/UPSERT string
assembly. The framework should offer this once.

### Goals

- **G1** — Lift generic CRUD into `PostgresToolkit` as first-class
  LLM-callable tools: `insert_row`, `upsert_row`, `update_row`, `delete_row`,
  `select_rows`. Exposed only when `read_only=False`.
- **G2** — Drive input validation from database metadata: per-table Pydantic
  models built dynamically from `TableMetadata.columns`, memoized via
  `functools.lru_cache` on a module-level helper.
- **G3** — Cache SQL templates per-instance under keys like
  `upsert_auth_programs_<conflict_hash>`, built lazily, cleared manually via
  `PostgresToolkit.reload_metadata(schema, table)`.
- **G4** — Extract UNIQUE constraints at warm-up via a new dialect hook
  (`SQLToolkit._get_unique_constraints_query`). Store on a new
  `TableMetadata.unique_constraints: List[List[str]]` attribute. Use PK as
  UPSERT default when `conflict_cols` is not provided.
- **G5** — Add `require_pk_in_where` + `primary_keys` kwargs to
  `QueryValidator.validate_sql_ast`; CRUD helpers default them to `True`
  for UPDATE/DELETE.
- **G6** — Enforce a per-instance table whitelist (`self.tables`) on the
  new CRUD methods (raw `execute_query` remains unchanged).
- **G7** — Add `PostgresToolkit.transaction()` async context manager so
  multi-table flows (`create_program`, `create_module`, `create_widget`)
  can group writes under one connection with commit/rollback semantics.
- **G8** — Refactor `NavigatorToolkit` to subclass `PostgresToolkit`. Drop
  `_query`, `_query_one`, `_exec`, `_get_db`, `_connection`,
  `_build_update`, and the top-level `AsyncPool`. Migrate constructor from
  `connection_params=dict` to `dsn=str` (breaking).
- **G9** — Preserve all LLM-facing tool names, schemas, and
  `confirm_execution` / `dry_run` guardrails on `NavigatorToolkit`.
  Authorization guardrails (`_check_program_access`, `_check_write_access`,
  `_require_superuser`, `_load_user_permissions`) stay intact.

### Non-Goals (explicitly out of scope)

- Reworking `navigator/schemas.py`. The LLM-facing Pydantic input schemas
  stay hand-written — they carry descriptions and cross-field validators
  that the auto-generated models don't replicate.
- Changing the LLM-facing tool surface of `NavigatorToolkit`
  (`create_program` / `create_module` / …). Same names, same inputs.
- Modifying `DatabaseQueryToolkit` / FEAT-105 paths. Different module
  tree (`parrot.tools.databasequery.*`), different class.
- Adding new database drivers, adding BigQuery/Influx CRUD, or extending
  `NavigatorToolkit` beyond the currently-whitelisted 13 tables.
- Deep transaction nesting (savepoints). Only top-level transactions.
- Persisting the prepared-statement cache across process restarts or
  adding TTL-based invalidation. Cache is in-memory, per-instance, cleared
  manually.
- Reusing `asyncdb.Model.makeModel` as the canonical write path (rejected in
  brainstorm Option C — cannot express arbitrary `ON CONFLICT` targets).

---

## 2. Architectural Design

### Overview

Lift generic CRUD into `PostgresToolkit` so the same primitives serve every
PG-backed agent, then refactor `NavigatorToolkit` to subclass
`PostgresToolkit` and delete its bespoke SQL plumbing. The new CRUD methods
operate on tables registered in `self.tables` (a whitelist), drive input
validation from `TableMetadata` via dynamic Pydantic models, and run
through templated SQL cached per-instance.

```
┌──────────────────────────────────────────────────────────────┐
│ NavigatorToolkit(PostgresToolkit)                            │
│                                                              │
│  LLM-facing tools: create_program / create_module / …        │
│  authorization guardrails: _check_*_access, _require_*       │
└────────────────────┬─────────────────────────────────────────┘
                     │ delegates writes to
                     ▼
┌──────────────────────────────────────────────────────────────┐
│ PostgresToolkit(SQLToolkit)                                  │
│                                                              │
│  New CRUD tools (gated by read_only):                        │
│    insert_row / upsert_row / update_row /                    │
│    delete_row / select_rows                                  │
│                                                              │
│  New internals:                                              │
│    transaction() · reload_metadata()                         │
│    _prepared_cache: dict[str, str]                           │
│    _get_or_build_template(op, schema, table, conflict_cols)  │
└────────┬─────────────────────────────┬───────────────────────┘
         │ reads metadata from         │ validates SQL via
         ▼                             ▼
┌──────────────────────┐       ┌────────────────────────────────┐
│ CachePartition       │       │ QueryValidator.validate_sql_ast│
│ (TableMetadata+PK+   │       │ + require_pk_in_where=True     │
│  unique_constraints) │       │ + primary_keys=meta.pks        │
└──────────┬───────────┘       └────────────────────────────────┘
           │ built by SQLToolkit._warm_table_cache
           │   + new _get_unique_constraints_query
           ▼
┌──────────────────────────────────────────────────────────────┐
│ module-level helper (parrot/bots/database/toolkits/_crud.py) │
│                                                              │
│ @functools.lru_cache(maxsize=256)                            │
│ _build_pydantic_model(model_name, columns_key_tuple) →       │
│     Type[BaseModel]                                          │
│                                                              │
│ _build_insert_sql / _build_upsert_sql /                      │
│ _build_update_sql / _build_delete_sql /                      │
│ _build_select_sql  →  (sql: str, param_order: list[str])     │
└──────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.bots.database.toolkits.postgres.PostgresToolkit` | extends | Adds CRUD tool methods + helpers |
| `parrot.bots.database.toolkits.sql.SQLToolkit` | extends | New `_get_unique_constraints_query` dialect hook; `_build_table_metadata` populates new field |
| `parrot.bots.database.toolkits.base.DatabaseToolkit` | extends | `exclude_tools` semantics extended in `__init__` when `read_only=True` (via subclasses, no base API change) |
| `parrot.bots.database.models.TableMetadata` | extends | New attribute `unique_constraints: List[List[str]]` |
| `parrot.bots.database.cache.CachePartition` | depends on | No change — stores richer `TableMetadata` transparently |
| `parrot.security.QueryValidator` | extends | `validate_sql_ast` gains two kwargs |
| `parrot_tools.navigator.NavigatorToolkit` | rewrites parent | Now subclasses `PostgresToolkit`; drops private SQL helpers |
| `parrot_tools.navigator.schemas` | no change | LLM input contract untouched |
| `asyncdb` (backend) | depends on | Uses existing `conn.execute(sql, *args)` / `conn.fetchrow` / `conn.fetch` / `conn.transaction()` |
| `pydantic>=2.12` | depends on | `create_model`, `field_validator` |
| `datamodel.types.MODEL_TYPES` | reuses | PG `data_type` string → Python type |
| `sqlglot` | reuses | `exp.Column` / `exp.Update` / `exp.Delete` AST walk for PK enforcement |

### Data Models

```python
# Extension to existing TableMetadata (parrot/bots/database/models.py:106)
@dataclass
class TableMetadata:
    # ... existing fields unchanged ...
    unique_constraints: List[List[str]] = field(default_factory=list)
    # Each inner list is one UNIQUE constraint's column set
    # (ordered by ordinal_position). Populated by SQLToolkit._build_table_metadata.
```

```python
# New per-module helper module: parrot/bots/database/toolkits/_crud.py
# Type alias documenting the cache key shape for _build_pydantic_model.
ColumnsKey = tuple[tuple[str, type, bool, bool], ...]
# Each tuple: (column_name, python_type, is_nullable, is_json)
# Used as the hashable second argument to the lru_cache'd builder.
```

```python
# Input shape for CRUD methods (documented, not a declared Pydantic class —
# the actual runtime input model is create_model()-generated per table).
#
# insert_row / upsert_row:
#   table: str                            # "schema.table" or "table" (uses primary_schema)
#   data: dict[str, Any]                  # validated through the dynamic model
#   conflict_cols: Optional[list[str]] = None  # UPSERT only; default = primary_keys
#   update_cols: Optional[list[str]] = None    # UPSERT only; default = all non-conflict cols in data
#   returning: Optional[list[str]] = None      # columns to RETURN; None = no RETURNING
#   conn: Optional[Any] = None            # existing transaction connection
#
# update_row:
#   table, data, where: dict[str, Any], returning, conn
#
# delete_row:
#   table, where: dict[str, Any], returning, conn
#
# select_rows:
#   table, where: Optional[dict[str, Any]] = None,
#   columns: Optional[list[str]] = None,  # default: all
#   order_by: Optional[list[str]] = None,
#   limit: Optional[int] = None,
#   conn: Optional[Any] = None
```

### New Public Interfaces

```python
# parrot/bots/database/toolkits/postgres.py — NEW public tool methods
class PostgresToolkit(SQLToolkit):
    async def insert_row(
        self,
        table: str,
        data: Dict[str, Any],
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]: ...

    async def upsert_row(
        self,
        table: str,
        data: Dict[str, Any],
        conflict_cols: Optional[List[str]] = None,
        update_cols: Optional[List[str]] = None,
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]: ...

    async def update_row(
        self,
        table: str,
        data: Dict[str, Any],
        where: Dict[str, Any],
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]: ...

    async def delete_row(
        self,
        table: str,
        where: Dict[str, Any],
        returning: Optional[List[str]] = None,
        conn: Optional[Any] = None,
    ) -> Dict[str, Any]: ...

    async def select_rows(
        self,
        table: str,
        where: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
        order_by: Optional[List[str]] = None,
        limit: Optional[int] = None,
        conn: Optional[Any] = None,
    ) -> List[Dict[str, Any]]: ...

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        """Yield an asyncdb connection inside a transaction block.

        Commits on normal exit, rolls back on exception. Nested calls raise
        (top-level only in this release).
        """
        ...

    async def reload_metadata(self, schema: str, table: str) -> None:
        """Purge and re-warm cached metadata + template entries for a table.

        Clears matching entries from self.cache_partition,
        self._prepared_cache, and calls _build_pydantic_model.cache_clear()
        (cache-wide — documented blast radius).
        """
        ...
```

```python
# parrot/security/query_validator.py — extended signature
class QueryValidator:
    @classmethod
    def validate_sql_ast(
        cls,
        query: str,
        dialect: Optional[str] = None,
        read_only: bool = True,
        require_pk_in_where: bool = False,   # NEW
        primary_keys: Optional[List[str]] = None,   # NEW
    ) -> Dict[str, Any]: ...
```

```python
# parrot/bots/database/toolkits/sql.py — new dialect hook
class SQLToolkit(DatabaseToolkit):
    def _get_unique_constraints_query(
        self, schema: str, table: str
    ) -> tuple[str, Dict[str, Any]]:
        """Return (SQL, params) for fetching UNIQUE constraints.

        Default queries information_schema.table_constraints +
        key_column_usage. Override in subclasses for PG-specific
        introspection.
        """
        ...
```

```python
# parrot_tools/navigator/toolkit.py — new parent class
class NavigatorToolkit(PostgresToolkit):   # was: AbstractToolkit
    def __init__(
        self,
        dsn: str,                                       # was: connection_params dict
        default_client_id: int = 1,
        user_id: Optional[int] = None,
        confirm_execution: bool = False,
        page_index: Optional[Any] = None,
        builder_groups: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            dsn=dsn,
            allowed_schemas=["public", "auth", "navigator"],
            primary_schema="navigator",
            tables=[
                "navigator.modules", "navigator.dashboards",
                "navigator.widgets_templates", "navigator.widgets",
                "navigator.modules_groups", "navigator.client_modules",
                "auth.programs", "auth.users", "auth.groups", "auth.clients",
                "auth.user_groups", "auth.program_groups", "auth.program_clients",
            ],
            read_only=False,
            **kwargs,
        )
        # ... existing NavigatorToolkit state (user_id, permissions cache) ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: QueryValidator PK-presence extension

- **Path**: `packages/ai-parrot/src/parrot/security/query_validator.py`
- **Responsibility**:
  - Extend `validate_sql_ast` with `require_pk_in_where: bool = False` and
    `primary_keys: Optional[List[str]] = None` keyword arguments.
  - In the DML-permitted branch (lines 274–282), after the existing "WHERE
    must exist" check, when `require_pk_in_where` is True: walk
    `root.args["where"].find_all(exp.Column)`, collect column names
    (case-insensitive), assert **non-empty intersection** with
    `primary_keys`. Reject with a clear message when empty.
  - Backward-compatible: default `require_pk_in_where=False` → no behaviour
    change for existing callers.
- **Depends on**: nothing (self-contained). `sqlglot` already imported.

### Module 2: TableMetadata.unique_constraints + introspection hook

- **Paths**:
  - `packages/ai-parrot/src/parrot/bots/database/models.py` — add
    `unique_constraints: List[List[str]] = field(default_factory=list)` to
    `TableMetadata` (after line 116).
  - `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` — add a
    new dialect hook `_get_unique_constraints_query(self, schema, table) ->
    tuple[str, dict]` alongside the existing `_get_primary_keys_query`
    (around line 424). Default query against
    `information_schema.table_constraints` +
    `key_column_usage` filtering by `constraint_type = 'UNIQUE'`.
  - Extend `SQLToolkit._build_table_metadata` (line 545) to execute the new
    query after PKs and populate the new field.
  - `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py` —
    optionally override with a PG-specific variant that joins
    `pg_constraint` for UNIQUE indexes as well (not just named UNIQUE
    constraints). If the default is sufficient, skip this override.
- **Depends on**: nothing (Module 1 is orthogonal).

### Module 3: Dynamic Pydantic model builder (lru_cache'd)

- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py`
  (new module).
- **Responsibility**:
  - Module-level function
    `_build_pydantic_model(model_name: str, columns_key: ColumnsKey) -> Type[BaseModel]`
    decorated with `@functools.lru_cache(maxsize=256)`. Uses
    `pydantic.create_model`. Fields: all optional by default; types from
    `datamodel.types.MODEL_TYPES`; `dict` / `list` for json/jsonb (flagged
    via `is_json` in the key tuple); `extra="forbid"` on the model config.
  - Helper `_columns_key_from_metadata(meta: TableMetadata) -> ColumnsKey`
    that converts `TableMetadata.columns` into a hashable tuple:
    `tuple((col["name"], MODEL_TYPES.get(col["type"], str), col["nullable"], col["type"] in {"json","jsonb","hstore"}) for col in meta.columns)`.
  - Unit-tested directly without needing a live DB.
- **Depends on**: Module 2 (uses extended `TableMetadata`, though just the
  existing `columns` attribute).

### Module 4: SQL template builders (pure functions)

- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py`
  (same new module as Module 3).
- **Responsibility**:
  - `_build_insert_sql(schema, table, columns, returning) -> (sql, param_order)`
  - `_build_upsert_sql(schema, table, columns, conflict_cols, update_cols, returning) -> (sql, param_order)`
  - `_build_update_sql(schema, table, set_columns, where_columns, returning) -> (sql, param_order)`
  - `_build_delete_sql(schema, table, where_columns, returning) -> (sql, param_order)`
  - `_build_select_sql(schema, table, columns, where_columns, order_by, limit) -> (sql, param_order)`
  - All use `DatabaseToolkit._validate_identifier` (base.py:168) for
    schema / table / column names; emit `$N::text::jsonb` casts for json
    columns; deterministic `param_order` list for positional asyncdb binding.
  - All pure functions — no I/O, no class state. Easy unit-test coverage.
- **Depends on**: nothing (pure string assembly).

### Module 5: PostgresToolkit CRUD tool methods + template cache + transaction + reload

- **Path**:
  `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py`
- **Responsibility**:
  - Initialize `self._prepared_cache: Dict[str, str] = {}` in
    `PostgresToolkit.__init__` (alongside existing super call).
  - Add private `_get_or_build_template(op, schema, table, **kwargs) -> str`
    that computes the cache key (includes conflict_cols / returning / where
    columns hash as applicable), calls the right `_build_*_sql` from
    `_crud.py` on miss, stores, returns.
  - Add private `_get_or_build_pydantic_model(meta: TableMetadata) -> Type[BaseModel]`
    that wraps `_crud._build_pydantic_model`.
  - Add private `_resolve_table(table: str) -> tuple[str, str, TableMetadata]`
    that accepts `"schema.table"` or `"table"`, checks whitelist, returns
    `(schema, table, meta)` or raises `ValueError`.
  - Implement `insert_row`, `upsert_row`, `update_row`, `delete_row`,
    `select_rows` per the signatures in Section 2. Each:
    1. `_resolve_table` to get schema/table/meta.
    2. Build / validate via Pydantic model from `_get_or_build_pydantic_model`.
    3. Build / lookup template via `_get_or_build_template`.
    4. For UPDATE/DELETE: call
       `QueryValidator.validate_sql_ast(sql, dialect="postgres",
       read_only=False, require_pk_in_where=True,
       primary_keys=meta.primary_keys)`; reject if unsafe.
    5. Execute via `conn` if passed, else acquire from the pool.
    6. When `returning` is non-None, use `conn.fetchrow` / `conn.fetch`.
  - Add `transaction()` `@asynccontextmanager` that acquires a connection
    from the existing `self._connection` (the `AsyncDB` instance), calls
    `conn.transaction()`, yields the connection, commits/rolls back.
  - Add `reload_metadata(schema, table)`: purge the entry in
    `self.cache_partition.schema_cache[schema].tables[table]` (and
    `hot_cache` key), drop matching keys in `self._prepared_cache`, call
    `_crud._build_pydantic_model.cache_clear()`. Does NOT re-warm eagerly;
    next CRUD call triggers lazy re-warm.
  - Extend `PostgresToolkit.exclude_tools` in `__init__` when
    `read_only=True`: append `"insert_row", "upsert_row", "update_row",
    "delete_row"`. `select_rows` stays visible (it's a read). This must
    happen **before** `AbstractToolkit._generate_tools()` runs (i.e. during
    `__init__`, not after) — confirmed by tools/toolkit.py:286–321.
- **Depends on**: Modules 1, 2, 3, 4.

### Module 6: NavigatorToolkit refactor to PostgresToolkit subclass

- **Path**:
  `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
- **Responsibility**:
  - Change parent: `class NavigatorToolkit(PostgresToolkit):` (was
    `AbstractToolkit`).
  - New `import`:
    `from parrot.bots.database.toolkits.postgres import PostgresToolkit`.
  - Rewrite `__init__` to accept `dsn: str` instead of
    `connection_params: dict`; pass `allowed_schemas`, `primary_schema`,
    `tables`, `read_only=False` to `super().__init__`. Retain
    `default_client_id`, `user_id`, `confirm_execution`, `page_index`,
    `builder_groups` fields. **Delete the 17 lines of
    `print(self.connection_params)` at lines 79–95.**
  - Remove: `_get_db`, `_connection`, `_query`, `_query_one`, `_exec`,
    `_build_update`, `self._db`, `self._db_lock`. Replace all call sites.
  - Replace SELECT-style lookups (`_query`, `_query_one`) with
    `self.select_rows(...)` where possible, falling back to raw
    `self.execute_query(sql, …)` for complex joins (e.g. the widget-templates
    search, program-structure traversal, search).
  - Replace INSERT sites (`auth.programs`, `navigator.modules`,
    `navigator.dashboards`, `navigator.widgets`) with `self.upsert_row(...)`
    calls passing the appropriate `conflict_cols` and `returning`.
  - Replace the permission-assignment INSERTs
    (`auth.program_clients`, `auth.program_groups`,
    `navigator.client_modules`, `navigator.modules_groups`) with
    `self.upsert_row(...)` inside an `async with self.transaction() as tx:`
    block. Pass `conn=tx` so they share the same transaction.
  - Replace `_build_update` callers with `self.update_row(table, data,
    where={"<pk>": pk_val})`. `confirm_execution` gating on UPDATE still
    returns the same `{"status": "confirm_execution", "query": sql,
    "params": […]}` shape; the SQL now comes from the template builder
    rather than inline assembly.

…(truncated)…
