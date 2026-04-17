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
  - **Keep intact**: authorization helpers (`_load_user_permissions`,
    `_check_program_access`, `_check_module_access`,
    `_check_client_access`, `_check_dashboard_access`,
    `_check_widget_access`, `_check_write_access`, `_require_superuser`,
    `_apply_scope_filter`, `_get_accessible_program_ids`,
    `_get_accessible_module_ids`, `_is_uuid`, `_to_uuid`, `_jsonb`,
    `_resolve_program_id`, `_resolve_module_id`, `_resolve_dashboard_id`,
    `_resolve_client_ids`). These stay as private helpers.
  - Override `async def stop(self) -> None:` so it calls `super().stop()`
    (inherited from `DatabaseToolkit`, which closes the `AsyncDB`
    connection) and then calls `self._invalidate_permissions()`.
  - Override `tool_prefix` back to `""` (empty) so LLM-visible tool names
    remain `create_program`, `create_module`, etc. (not `db_create_program`).
    `DatabaseToolkit.tool_prefix = "db"` is the default — the override
    preserves the current public contract.
- **Depends on**: Module 5.

### Module 7: Example + docs update

- **Paths**:
  - `examples/navigator_agent.py` — migrate constructor call to
    `NavigatorToolkit(dsn=…)`.
  - Any internal tool registry or loader that instantiates
    `NavigatorToolkit` with `connection_params=…` (grep for call sites).
- **Responsibility**: compile-time + runtime parity under the new
  constructor.
- **Depends on**: Module 6.

### Module 8: Unit + integration tests

- **Paths**:
  - `tests/unit/test_query_validator_pk.py` (new) — covers Module 1.
  - `tests/unit/test_table_metadata_unique.py` (new) — covers Module 2.
  - `tests/unit/test_crud_helpers.py` (new) — covers Modules 3 + 4
    (pure unit: Pydantic model building + SQL template assembly).
  - `tests/unit/test_postgres_toolkit.py` (extend existing) — covers
    Module 5: CRUD methods (mock asyncdb connection), `read_only`
    visibility gating, whitelist rejection, `transaction()` context
    manager, `reload_metadata()`.
  - `tests/integration/test_navigator_toolkit_refactor.py` (new, if a PG
    fixture is available — otherwise skip-marked) — smoke-tests
    `create_program` / `create_module` / `create_dashboard` /
    `create_widget` against a live Postgres. If the existing suite has
    no PG fixture, document how to run this locally and mark as
    `pytest.mark.integration`.
- **Depends on**: Modules 1–6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_validate_sql_ast_pk_presence_passes_with_pk_in_where` | Module 1 | `UPDATE t SET x=1 WHERE id=1` accepted when `primary_keys=["id"]`, `require_pk_in_where=True` |
| `test_validate_sql_ast_pk_presence_rejects_non_pk_where` | Module 1 | `UPDATE t SET x=1 WHERE status='x'` rejected when `primary_keys=["id"]` |
| `test_validate_sql_ast_pk_presence_accepts_any_pk_of_composite` | Module 1 | Composite PK `["a","b"]`, WHERE only `a=1` → accepted (at least one PK col present) |
| `test_validate_sql_ast_pk_presence_backcompat_default_false` | Module 1 | Calling without the new kwarg is identical to the pre-feature behaviour |
| `test_validate_sql_ast_pk_presence_delete` | Module 1 | Same policy applies to DELETE |
| `test_table_metadata_unique_constraints_default_empty` | Module 2 | Existing callers see `unique_constraints == []` when dialect hook returns nothing |
| `test_sqltoolkit_build_table_metadata_populates_unique` | Module 2 | With a stubbed `_execute_asyncdb`, metadata contains parsed unique sets |
| `test_build_pydantic_model_lru_hits` | Module 3 | Two calls with identical `columns_key` return the same class (`cache_info().hits >= 1`) |
| `test_build_pydantic_model_rejects_unknown_field` | Module 3 | Generated model rejects a field not in the table (extra="forbid") |
| `test_build_pydantic_model_jsonb_accepts_dict` | Module 3 | `jsonb` column accepts dict payload |
| `test_build_insert_sql_no_returning` | Module 4 | Correct INSERT SQL + param_order for common columns |
| `test_build_upsert_sql_conflict_cols_default_to_pk` | Module 4 | When `conflict_cols` is None, PKs are used; SET clause covers non-conflict cols |
| `test_build_upsert_sql_explicit_conflict_cols` | Module 4 | Composite conflict target emits `ON CONFLICT (a, b) DO UPDATE SET c = EXCLUDED.c` |
| `test_build_update_sql_jsonb_cast` | Module 4 | JSON cols emit `$N::text::jsonb` |
| `test_build_select_sql_with_where_and_order` | Module 4 | WHERE + ORDER BY + LIMIT formed deterministically |
| `test_postgres_toolkit_insert_row_whitelist_rejection` | Module 5 | `insert_row("public.foo", …)` when `public.foo` not in `tables` → `ValueError` |
| `test_postgres_toolkit_insert_row_validates_input` | Module 5 | Unknown field in `data` raises pydantic `ValidationError` |
| `test_postgres_toolkit_upsert_row_uses_cached_template_on_second_call` | Module 5 | Second call hits `_prepared_cache` (mock asserts template builder called once) |
| `test_postgres_toolkit_update_row_blocks_non_pk_where` | Module 5 | `require_pk_in_where` propagates; mock validator returns rejection |
| `test_postgres_toolkit_transaction_commits_on_success` | Module 5 | Mock asyncdb transaction commits |
| `test_postgres_toolkit_transaction_rolls_back_on_exception` | Module 5 | Raises inside `async with` → rollback called |
| `test_postgres_toolkit_read_only_hides_write_tools` | Module 5 | `read_only=True` → `get_tools()` contains `select_rows` but no insert/upsert/update/delete |
| `test_postgres_toolkit_read_only_false_exposes_write_tools` | Module 5 | Inverse check |
| `test_postgres_toolkit_reload_metadata_clears_entries` | Module 5 | After reload, `_prepared_cache` has no keys for that table; `_build_pydantic_model.cache_info().currsize` decreases |
| `test_navigator_toolkit_init_accepts_dsn_only` | Module 6 | `NavigatorToolkit(dsn="postgres://…")` constructs cleanly |
| `test_navigator_toolkit_init_rejects_connection_params` | Module 6 | Passing `connection_params=` raises `TypeError` (breaking change documented) |
| `test_navigator_toolkit_tool_names_unchanged` | Module 6 | `tool_prefix=""` → `get_tools()` names remain `create_program`, `create_module`, … |
| `test_navigator_toolkit_authorization_still_enforced` | Module 6 | `_check_program_access` behaves identically after refactor (mock permissions load) |

### Integration Tests

| Test | Description |
|---|---|
| `test_navigator_create_program_end_to_end` | Creates a program, verifies `auth.programs`, `auth.program_clients`, `auth.program_groups` rows; idempotency re-run returns `already_existed=True` |
| `test_navigator_create_module_transaction_atomicity` | Forces failure mid-flow (mock after first `upsert_row` inside `transaction()`); all writes rolled back |
| `test_navigator_create_dashboard_returns_dashboard_id` | RETURNING clause threads UUID back to the caller |
| `test_navigator_update_widget_pk_required` | `update_widget(widget_id=uuid, …)` succeeds; manually-crafted update without PK rejected |
| `test_postgres_toolkit_crud_on_fresh_table` | Warm-up a test table, INSERT/UPSERT/UPDATE/DELETE round-trip through the new tools |

### Test Data / Fixtures

```python
# tests/conftest.py (extend) — optional
@pytest.fixture
async def pg_toolkit_with_fixture_table(pg_dsn: str):
    """Spin up a PostgresToolkit pointing at a scratch table.

    Creates:
        CREATE TABLE test_crud (id SERIAL PRIMARY KEY, name TEXT UNIQUE,
                                 data JSONB DEFAULT '{}');
    Yields a started toolkit; drops the table on teardown.
    """
    ...

@pytest.fixture
def fake_table_metadata() -> TableMetadata:
    """Hand-built TableMetadata for unit tests that don't hit a DB."""
    return TableMetadata(
        schema="test",
        tablename="fixture",
        table_type="BASE TABLE",
        full_name='"test"."fixture"',
        columns=[
            {"name": "id", "type": "integer", "nullable": False, "default": None},
            {"name": "name", "type": "varchar", "nullable": False, "default": None},
            {"name": "data", "type": "jsonb", "nullable": True, "default": "'{}'"},
        ],
        primary_keys=["id"],
        unique_constraints=[["name"]],
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `QueryValidator.validate_sql_ast(query, …, require_pk_in_where=True, primary_keys=["id"])` rejects `UPDATE t SET x=1 WHERE status='y'` and accepts `UPDATE t SET x=1 WHERE id=5`, with matching DELETE behaviour.
- [ ] Default `require_pk_in_where=False` preserves existing validator output byte-for-byte (verified by comparing against a captured baseline).
- [ ] `TableMetadata.unique_constraints` is populated on any table warmed through `SQLToolkit._build_table_metadata` when the hook returns results; existing callers see an empty list when unchanged.
- [ ] `PostgresToolkit(dsn=…, tables=[…], read_only=False).get_tools()` exposes five new LLM tools: `db_insert_row`, `db_upsert_row`, `db_update_row`, `db_delete_row`, `db_select_rows` (prefixed via the existing `tool_prefix="db"`).
- [ ] `PostgresToolkit(…, read_only=True).get_tools()` exposes `db_select_rows` only (no insert/upsert/update/delete).
- [ ] CRUD methods reject writes to tables not in `self.tables` with `ValueError` whose message includes the rejected `schema.table`.
- [ ] CRUD methods reject unknown fields in `data` with `pydantic.ValidationError`.
- [ ] `_build_pydantic_model.cache_info().hits` is > 0 after repeated calls on the same table shape (LRU functioning).
- [ ] `upsert_row(..., conflict_cols=None)` falls back to `TableMetadata.primary_keys` as the conflict target; explicit `conflict_cols=[…]` overrides.
- [ ] `update_row` / `delete_row` invoke `QueryValidator.validate_sql_ast` with `require_pk_in_where=True`, using the table's primary keys.
- [ ] `async with toolkit.transaction() as tx:` yields an asyncdb connection; exception inside the block triggers rollback; normal exit commits; nested `transaction()` raises.
- [ ] `reload_metadata("schema", "table")` removes the entry from `cache_partition` (both `schema_cache` and `hot_cache`), clears matching keys in `_prepared_cache`, and calls `_build_pydantic_model.cache_clear()`.
- [ ] `NavigatorToolkit` constructor accepts `dsn: str` and rejects `connection_params=` (breaking change flagged in release notes).
- [ ] `NavigatorToolkit` inherits from `PostgresToolkit` (`issubclass(NavigatorToolkit, PostgresToolkit) is True`).
- [ ] `NavigatorToolkit.get_tools()` still exposes the exact set of tool names it exposes today (regression test against a captured list): `create_program`, `update_program`, `get_program`, `list_programs`, `create_module`, `update_module`, `get_module`, `list_modules`, `create_dashboard`, `update_dashboard`, `get_dashboard`, `list_dashboards`, `clone_dashboard`, `create_widget`, `update_widget`, `get_widget`, `list_widgets`, `assign_module_to_client`, `assign_module_to_group`, `list_widget_types`, `list_widget_categories`, `list_clients`, `list_groups`, `get_widget_schema`, `find_widget_templates`, `search_widget_docs`, `get_full_program_structure`, `search`.
- [ ] `NavigatorToolkit` no longer contains `_query`, `_query_one`, `_exec`, `_get_db`, `_connection`, `_build_update` as attributes (verified via AST or `hasattr` tests).
- [ ] The 17 duplicated `print(self.connection_params)` statements at `toolkit.py:79–95` are removed.
- [ ] Authorization guardrails (`_check_program_access`, `_check_write_access`, `_require_superuser`, `_load_user_permissions`) remain functionally identical — verified by an existing regression test or one added for this feature.
- [ ] `examples/navigator_agent.py` runs to completion with the new constructor (manual smoke check; linked in PR description).
- [ ] All new unit tests pass: `pytest tests/unit/test_query_validator_pk.py tests/unit/test_table_metadata_unique.py tests/unit/test_crud_helpers.py tests/unit/test_postgres_toolkit.py -v`.
- [ ] Integration tests pass against a live Postgres (or are clearly skip-marked when no DSN is available): `pytest tests/integration/ -v -m integration`.
- [ ] No module outside `parrot.bots.database.*`, `parrot.security.*`, or `parrot_tools.navigator.*` is modified (verified by `git diff --name-only` scope).
- [ ] No regression in FEAT-105's `DatabaseQueryToolkit`: `pytest tests/unit/test_database_query_toolkit.py` remains green.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.**
> This section is the single source of truth for what exists today.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying via `grep` / `read`.

### Verified Imports

```python
# All confirmed by read/grep during brainstorm Round 2 + spec verification:
from parrot.bots.database.toolkits.postgres import PostgresToolkit
# verified at: packages/ai-parrot/src/parrot/bots/database/toolkits/__init__.py:11

from parrot.bots.database.toolkits.sql import SQLToolkit
# verified at: packages/ai-parrot/src/parrot/bots/database/toolkits/__init__.py:10

from parrot.bots.database.toolkits.base import DatabaseToolkit, DatabaseToolkitConfig
# verified at: packages/ai-parrot/src/parrot/bots/database/toolkits/__init__.py:9

from parrot.bots.database.models import (
    TableMetadata, SchemaMetadata, QueryExecutionResponse,
)
# verified at: packages/ai-parrot/src/parrot/bots/database/models.py:86, 106, 182

from parrot.bots.database.cache import CachePartition
# verified at: packages/ai-parrot/src/parrot/bots/database/cache.py:45

from parrot.security import QueryValidator, QueryLanguage
# verified at: packages/ai-parrot/src/parrot/security/__init__.py:11, 12, 20, 21

from parrot.tools import AbstractToolkit, tool_schema
# verified at: packages/ai-parrot/src/parrot/tools/__init__.py:142, 143, 211, 213

from parrot_tools.navigator import NavigatorToolkit
# verified at: packages/ai-parrot-tools/src/parrot_tools/navigator/__init__.py:25

from asyncdb.models import Model
# verified present at: .venv/lib/python3.11/site-packages/asyncdb/models/__init__.py (Model.makeModel classmethod)

from datamodel.types import MODEL_TYPES
# verified at: .venv/lib/python3.11/site-packages/datamodel/types.py
# 24 entries: {'boolean','integer','bigint','float','character varying','string',
#              'varchar','byte','bytea','Array','hstore','character varying[]',
#              'numeric','date','timestamp with time zone','time',
#              'timestamp without time zone','uuid','json','jsonb','text',
#              'serial','bigserial','inet'}

from pydantic import create_model, Field, BaseModel, field_validator
# verified: pydantic 2.12.5 installed

import sqlglot
from sqlglot import exp
# verified: sqlglot already used by parrot.security.query_validator
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    def __init__(                                               # line 22
        self,
        dsn: str,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        tables: Optional[List[str]] = None,
        read_only: bool = True,
        backend: str = "asyncdb",
        **kwargs: Any,
    ) -> None: ...
    def _get_explain_prefix(self) -> str: ...                   # line 47
    def _get_information_schema_query(                          # line 50
        self, search_term: str, schemas: List[str],
    ) -> tuple[str, Dict[str, Any]]: ...
    def _get_columns_query(                                     # line 81
        self, schema: str, table: str,
    ) -> tuple[str, Dict[str, Any]]: ...
    def _build_sqlalchemy_dsn(self, raw_dsn: str) -> str: ...   # line 103
    def _get_asyncdb_driver(self) -> str: ...                   # line 111  (returns "pg")
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
class SQLToolkit(DatabaseToolkit):
    exclude_tools: tuple[str, ...] = (                          # line 51
        "start", "stop", "cleanup",
        "get_table_metadata", "health_check",
    )
    def __init__(                                               # line 59
        self,
        dsn: str,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        tables: Optional[List[str]] = None,
        read_only: bool = True,
        backend: str = "asyncdb",
        cache_partition: Optional[CachePartition] = None,
        retry_config: Optional[QueryRetryConfig] = None,
        database_type: str = "postgresql",
        **kwargs: Any,
    ) -> None: ...
    async def search_schema(                                    # line 89
        self, search_term: str,
        schema_name: Optional[str] = None, limit: int = 10,
    ) -> List[TableMetadata]: ...
    async def execute_query(                                    # line 162
        self, query: str, limit: int = 1000, timeout: int = 30,
    ) -> QueryExecutionResponse: ...
    def _check_query_safety(self, sql: str) -> Optional[str]: ...  # line 293
    async def _warm_table_cache(self) -> None: ...              # line 322
    def _get_primary_keys_query(                                # line 424
        self, schema: str, table: str,
    ) -> tuple[str, Dict[str, Any]]: ...
    async def _execute_asyncdb(                                 # line 451
        self, sql: str, limit: int = 1000, timeout: int = 30,
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]: ...
    async def _build_table_metadata(                            # line 545
        self, schema: str, table: str, table_type: str,
        comment: Optional[str] = None,
    ) -> Optional[TableMetadata]: ...
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
class DatabaseToolkit(AbstractToolkit, ABC):
    tool_prefix: str = "db"                                     # line 80
    exclude_tools: tuple[str, ...] = (                          # line 83
        "start", "stop", "cleanup",
        "get_table_metadata", "health_check",
    )
    def __init__(                                               # line 91
        self,
        dsn: str,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        tables: Optional[List[str]] = None,
        read_only: bool = True,
        backend: str = "asyncdb",
        cache_partition: Optional[CachePartition] = None,
        retry_config: Optional[QueryRetryConfig] = None,
        database_type: str = "postgresql",
        **kwargs: Any,
    ) -> None: ...
    async def start(self) -> None: ...                          # line 188
    async def stop(self) -> None: ...                           # line 218
    async def cleanup(self) -> None: ...                        # line 237
    async def health_check(self) -> bool: ...                   # line 241
    async def get_table_metadata(                               # line 272
        self, schema_name: str, table_name: str,
    ) -> Optional[TableMetadata]: ...
    @staticmethod
    def _validate_identifier(name: str) -> str: ...             # line 167
    async def _connect_asyncdb(self) -> None: ...               # line 336
```

```python
# packages/ai-parrot/src/parrot/bots/database/models.py
@dataclass
class TableMetadata:                                            # line 106
    schema: str                                                 # line 108
    tablename: str                                              # line 109
    table_type: str                                             # line 110
    full_name: str                                              # line 111
    comment: Optional[str] = None                               # line 112
    columns: List[Dict[str, Any]] = field(default_factory=list) # line 113
    primary_keys: List[str] = field(default_factory=list)       # line 114
    foreign_keys: List[Dict[str, Any]] = field(default_factory=list)  # line 115
    indexes: List[Dict[str, Any]] = field(default_factory=list) # line 116
    row_count: Optional[int] = None                             # line 117
    sample_data: List[Dict[str, Any]] = field(default_factory=list)  # line 118
    # ↓ this feature adds:
    # unique_constraints: List[List[str]] = field(default_factory=list)

class QueryExecutionResponse(BaseModel):                        # line 182
    success: bool
    data: Optional[Any] = None
    row_count: int = 0
    execution_time_ms: float
    columns: List[str] = Field(default_factory=list)
    query_plan: Optional[str] = None
    error_message: Optional[str] = None
    schema_used: str
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
```

```python
# packages/ai-parrot/src/parrot/security/query_validator.py
class QueryValidator:                                           # line 29
    @staticmethod
    def validate_sql_query(query: str) -> Dict[str, Any]: ...   # line 33 (legacy regex)
    @classmethod
    def validate_sql_ast(                                       # line 164
        cls,
        query: str,
        dialect: Optional[str] = None,
        read_only: bool = True,
    ) -> Dict[str, Any]: ...
    # This feature ADDS two kwargs to validate_sql_ast:
    #   require_pk_in_where: bool = False
    #   primary_keys: Optional[List[str]] = None
    # DML-permitted branch is at lines 274-282:
    #   if isinstance(root, (exp.Update, exp.Delete)):
    #       if root.args.get('where') is None: → reject "WHERE clause required"
    # Extended logic: when require_pk_in_where=True and WHERE is present,
    # walk root.args['where'].find_all(exp.Column), collect column names,
    # assert intersection with primary_keys; reject if empty.
```

```python
# packages/ai-parrot/src/parrot/bots/database/cache.py
class CachePartition:                                           # line 45
    def __init__(                                               # line 57
        self,
        namespace: str,
        lru_maxsize: int = 500, lru_ttl: int = 1800,
        redis_ttl: int = 3600,
        redis_pool: Any = None,
        vector_store: Optional["AbstractStore"] = None,
    ): ...
    # Public methods relevant to this feature:
    #   async def get_table_metadata(schema, table) -> Optional[TableMetadata]
    #   async def store_table_metadata(metadata: TableMetadata) -> None
    #   async def search_similar_tables(schemas, search_term, limit) -> list[TableMetadata]
    # Internal state:
    #   self.hot_cache: TTLCache   (LRU)
    #   self.schema_cache: Dict[str, SchemaMetadata]
```

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    tool_prefix: str = ""                                       # default
    exclude_tools: tuple[str, ...] = ()                         # line 177
    def _generate_tools(self) -> None:                          # line 286
        # Inspects dir(self), skips _*, skips names in exclude_tools,
        # creates tools from coroutine functions.
        # CRITICAL: exclude_tools is read here — PostgresToolkit
        # must extend it BEFORE this runs (during __init__).
        ...
```

```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
class NavigatorToolkit(AbstractToolkit):                        # line 40  (parent changes to PostgresToolkit)
    def __init__(                                               # line 52
        self,
        connection_params: Optional[Dict[str, Any]] = None,     # ← breaking change: becomes `dsn: str`
        default_client_id: int = 1,
        user_id: Optional[int] = None,
        confirm_execution: bool = False,
        page_index: Optional[Any] = None,
        builder_groups: Optional[List[str]] = None,
        **kwargs,
    ): ...
    # Helpers REMOVED by this feature:
    async def stop(self) -> None: ...                           # line 99  (replaced; delegates to super)
    async def _get_db(self) -> AsyncPool: ...                   # line 120 REMOVE
    async def _connection(self): ...                            # line 135 REMOVE (context manager)
    async def _query(self, sql, params=None): ...               # line 147 REMOVE
    async def _query_one(self, sql, params=None): ...           # line 154 REMOVE
    async def _exec(self, sql, params=None): ...                # line 161 REMOVE
    async def _build_update(                                    # line 284 REMOVE
        self, table, pk_col, pk_val, data, confirm_execution=False,
        include_updated_at=False,
    ) -> dict: ...
    # Helpers RETAINED (authorization and utility):
    def _jsonb(self, value) -> Optional[str]: ...               # line 168 KEEP
    @staticmethod
    def _is_uuid(value) -> bool: ...                            # line 174 KEEP
    @staticmethod
    def _to_uuid(value) -> Optional[uuid.UUID]: ...             # line 183 KEEP
    async def _resolve_program_id(...): ...                     # line 198 KEEP
    async def _resolve_module_id(...): ...                      # line 211 KEEP
    async def _resolve_dashboard_id(...): ...                   # line 230 KEEP
    async def _resolve_client_ids(...): ...                     # line 250 KEEP
    async def _load_user_permissions(self) -> None: ...         # line 331 KEEP
    async def _check_program_access(self, program_id): ...      # line 408 KEEP
    async def _check_client_access(self, client_id): ...        # line 423 KEEP
    async def _check_module_access(self, module_id, ...): ...   # line 439 KEEP
    async def _check_dashboard_access(self, dashboard_id): ...  # line 474 KEEP
    async def _check_widget_access(self, widget_id): ...        # line 493 KEEP
    async def _require_superuser(self) -> None: ...             # line 514 KEEP
    async def _check_write_access(self, program_id): ...        # line 527 KEEP
    def _get_accessible_program_ids(self): ...                  # line 545 KEEP
    def _get_accessible_module_ids(self): ...                   # line 551 KEEP
    def _apply_scope_filter(self, conds, params, idx, entity): ...  # line 557 KEEP
    # Public LLM tools (names frozen — must not change):
    async def create_program(...): ...                          # line 591
    async def update_program(...): ...                          # line 727
    async def get_program(...): ...                             # line 738
    async def list_programs(...): ...                           # line 758
    async def create_module(...): ...                           # line 784
    async def update_module(...): ...                           # line 950
    async def get_module(...): ...                              # line 964
    async def list_modules(...): ...                            # line 986
    async def create_dashboard(...): ...                        # line 1022
    async def update_dashboard(...): ...                        # line 1118
    async def get_dashboard(...): ...                           # line 1131
    async def list_dashboards(...): ...                         # line 1148
    async def clone_dashboard(...): ...                         # line 1178
    async def create_widget(...): ...                           # line 1266
    async def update_widget(...): ...                           # line 1374
    async def get_widget(...): ...                              # line 1415
    async def list_widgets(...): ...                            # line 1437
    async def assign_module_to_client(...): ...                 # line 1470
    async def assign_module_to_group(...): ...                  # line 1485
    async def list_widget_types(...): ...                       # line 1503
    async def list_widget_categories(...): ...                  # line 1511
    async def list_clients(...): ...                            # line 1519
    async def list_groups(...): ...                             # line 1530
    async def get_widget_schema(...): ...                       # line 1552
    async def find_widget_templates(...): ...                   # line 1616
    async def search_widget_docs(...): ...                      # line 1649
    async def get_full_program_structure(...): ...              # line 1684
    async def search(...): ...                                  # line 1732
```

```python
# asyncdb.models.Model (verified via live introspection during brainstorm)
class Model(...):
    @classmethod
    async def makeModel(                                        # present
        cls,
        name: str,
        schema: str = "public",
        fields: list = None,
        db: Awaitable = None,
    ) -> type: ...
    # Instance methods: .insert(), .save(), .update(), .delete(_filter=None, **kwargs),
    #                   .get(**kwargs), .fetch(), .select(), .filter(**kwargs),
    #                   .all()
    # Meta attrs: name, schema, connection, frozen, credentials, dsn, driver, ...
    #
    # NOTE: asyncdb.Model is RESEARCHED for reference; this feature does NOT use
    # it as the canonical write path (see brainstorm Option C rejection).
```

```python
# pydantic 2.12.5
from pydantic import create_model, Field, BaseModel, ConfigDict, field_validator
# create_model(model_name: str, __base__=None, __config__=None, __doc__=None,
#              __validators__=None, **fields) -> type[BaseModel]
# Field spec: each field is (type, default) or (type, Field(...))
# For extra="forbid" on dynamic models, pass __config__=ConfigDict(extra="forbid").
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_crud._build_pydantic_model` | `pydantic.create_model` | direct call | pydantic 2.12.5 |
| `_crud._build_*_sql` helpers | `DatabaseToolkit._validate_identifier` | static method call | base.py:167 |
| `PostgresToolkit._get_or_build_pydantic_model` | `CachePartition.get_table_metadata` | method call | cache.py |
| `PostgresToolkit.insert_row` / `upsert_row` / `update_row` / `delete_row` | `QueryValidator.validate_sql_ast(require_pk_in_where=True, …)` | method call | query_validator.py:164 (extended) |
| `PostgresToolkit.transaction()` | `asyncdb.AsyncDB.connection().transaction()` | async context manager | asyncdb backend (existing) |
| `PostgresToolkit._warm_table_cache` | `_build_table_metadata` (extended) | override of SQLToolkit hook | sql.py:322, 545 |
| `NavigatorToolkit.__init__` | `PostgresToolkit.__init__(dsn, tables, allowed_schemas, primary_schema, read_only)` | super call | postgres.py:22 |
| `NavigatorToolkit.create_program` | `self.upsert_row("auth.programs", data, conflict_cols=["program_slug"], returning=[...])` | method call | new in Module 5 |
| `NavigatorToolkit.create_program` | `async with self.transaction() as tx:` for multi-table writes | async ctx mgr | new in Module 5 |

### Does NOT Exist (Anti-Hallucination)

- ~~`PostgresToolkit.insert_row` / `upsert_row` / `update_row` / `delete_row` / `select_rows`~~ — do not exist today; added in this feature.
- ~~`PostgresToolkit.transaction()`~~ — does not exist.
- ~~`PostgresToolkit.reload_metadata()`~~ — does not exist.
- ~~`SQLToolkit._get_unique_constraints_query`~~ — hook does not exist.
- ~~`TableMetadata.unique_constraints`~~ — attribute does not exist on the current dataclass.
- ~~`QueryValidator.validate_sql_ast(require_pk_in_where=…, primary_keys=…)`~~ — these kwargs do not exist.
- ~~`parrot.bots.database.toolkits._crud`~~ — module does not exist (created in Module 3/4).
- ~~`NavigatorToolkit(PostgresToolkit)`~~ — today it inherits `AbstractToolkit` directly.
- ~~`NavigatorToolkit(dsn=…)`~~ — current constructor takes `connection_params: dict`.
- ~~`DatabaseToolkit._whitelist_check`~~ — no table whitelist enforcement today; added as private method in Module 5 (`_resolve_table`).
- ~~`asyncdb.Model.upsert`~~ — no first-class UPSERT; `Model.save()` does not support `ON CONFLICT (cols) DO UPDATE SET …` with arbitrary conflict targets.
- ~~`parrot.bots.database.toolkits.navigator`~~ — no such module; NavigatorToolkit lives in the separate `ai-parrot-tools` package.
- ~~`datamodel.BaseModel.make_model(..., db=...)`~~ — does NOT accept a `db=` parameter. Only `asyncdb.Model.makeModel` does.
- ~~`methodtools.lru_cache`~~ — not a project dependency; this feature uses `functools.lru_cache` only.
- ~~`AbstractToolkit.tool_prefix` other than `""`~~ — default is empty string; `DatabaseToolkit` overrides it to `"db"` at base.py:80.
- ~~`QueryValidator.validate_sql_query` being AST-aware~~ — the regex-based validator at line 33 is the legacy fallback; this feature extends `validate_sql_ast` (line 164), not `validate_sql_query`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `async`/`await` throughout — no blocking I/O.
- Pydantic models for all structured data (dynamic ones via `create_model`).
- Logging via `self.logger` — avoid `print`. Explicitly remove the 17
  duplicated `print(self.connection_params)` statements at
  `toolkit.py:79–95`.
- Google-style docstrings on every new public method, including short
  examples in the `insert_row` / `upsert_row` docstrings (these become
  the LLM's tool description).
- `exclude_tools` must be a **tuple**, not a list; extend by tuple
  concatenation inside `__init__` before `super().__init__` runs (or
  before `_generate_tools()` is called). Double-check the order of
  operations against `AbstractToolkit.__init__` path.
- Use `DatabaseToolkit._validate_identifier` for every schema/table/column
  name that reaches a SQL string to prevent injection via metadata lookup.
- Use asyncdb's `conn.execute(sql, *args)` for writes without RETURNING,
  `conn.fetchrow(sql, *args)` for single-row RETURNING, `conn.fetch(sql, *args)`
  for multi-row. No string interpolation of values.
- `jsonb` columns: the template builder emits `$N::text::jsonb`; the
  execution layer calls `json.dumps(value)` on the Python dict/list
  before binding. Matches the existing NavigatorToolkit pattern.
- Module-level `functools.lru_cache(maxsize=256)` on
  `_build_pydantic_model` — the function must take only hashable positional
  args; `self` is NOT a parameter (that's why it lives at module level).

### Known Risks / Gotchas

- **`exclude_tools` read timing.** `AbstractToolkit._generate_tools()` reads
  `self.exclude_tools` once; if `PostgresToolkit.__init__` mutates it **after**
  `super().__init__()` that triggers `_generate_tools`, write tools will still
  be exposed on read-only instances. **Mitigation**: mutate `exclude_tools`
  **before** `super().__init__(**kwargs)` runs. Verified against
  tools/toolkit.py:286–321.
- **asyncdb `conn.execute` vs `conn.query` for RETURNING.** `conn.execute`
  does not return rows on asyncpg; `conn.fetchrow` / `conn.fetch` does.
  Current `SQLToolkit._execute_asyncdb` uses `conn.query(sql)` — read-only
  path. The new CRUD path must branch on whether `returning` is non-None.
- **Pydantic `extra="forbid"` breaks the `**kwargs` tolerance.** The
  existing NavigatorToolkit method bodies pass `**kwargs` through; the
  dynamic per-table validator rejecting unknown keys will surface real
  bugs in the callers. **Mitigation**: on first pass, run `data =
  {k: v for k, v in data.items() if k in meta_columns}` inside
  `NavigatorToolkit.*` call sites, and add a followup to tighten the
  schema validators instead.
- **UUID vs str for `dashboard_id` / `widget_id`.** asyncpg binds
  `uuid.UUID` objects, not strings with `::uuid` cast. `NavigatorToolkit._to_uuid`
  already handles this; the new `update_row` / `delete_row` must call it
  on PK binds. The template builder itself does not know the column is
  UUID — the Python type (from `MODEL_TYPES["uuid"] = uuid.UUID`) ensures
  Pydantic coerces; the execution layer trusts the validated object.
- **`_generate_tools` caches results.** If the subclass re-reads
  `exclude_tools` later, tools are already registered. Tests must assert
  `get_tools()` shape after `start()` / `await toolkit.start()`.
- **`functools.lru_cache.cache_clear()` nukes the whole cache.** Per the
  brainstorm's LRU-vs-dict tradeoff, `reload_metadata` accepts this
  blast-radius. Log a `self.logger.info("Cleared Pydantic model cache — N entries")`
  so operators see it.
- **Transaction connection type mismatch.** asyncdb's `AsyncDB` returns
  different connection wrappers depending on the driver. `PostgresToolkit`
  uses `pg` (asyncpg-backed); the `conn.transaction()` context manager is
  present on that driver. A `_get_asyncdb_driver` check at `transaction()`
  entry guards against accidental BigQuery use.
- **FEAT-105 concurrency.** FEAT-105's tasks (TASK-733..738) touch
  `parrot.tools.database` — a disjoint tree from `parrot.bots.database`.
  No merge conflict expected; still advise merging FEAT-105 first if it's
  closer to completion.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.12` | `create_model`, `ConfigDict`, `field_validator` |
| `sqlglot` | already present | AST walk for PK-presence check |
| `asyncdb` | `>=2.15` (installed 2.15.3) | `conn.execute` / `conn.fetchrow` / `conn.transaction()`; `Model.makeModel` signature reference |
| `datamodel` | already present (0.10.20) | `datamodel.types.MODEL_TYPES` PG→Python map |
| `functools` | stdlib | `lru_cache` |
| `contextlib` | stdlib | `asynccontextmanager` for `transaction()` |

No new third-party packages introduced.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Where should the PG-type → Python-type map live long-term? Reusing `datamodel.types.MODEL_TYPES` is the shortest path, but couples us to `datamodel`'s choice of `importlib._bootstrap.uint64` for `bigint`. Do we want a parrot-owned map under `parrot/bots/database/` to decouple? — *Owner: Jesus Lara*: parrot-owned the map.
- [x] `RETURNING` on UPSERT when the row existed and nothing changed: PG returns the new row only if `DO UPDATE` actually fires. The current Navigator idempotency path reads back with a second SELECT. Should `PostgresToolkit.upsert_row` formalize auto-fallback to SELECT when RETURNING yields 0 rows, or leave it to the caller? — *Owner: Jesus Lara*: formalize the idempotency.
- [x] `confirm_execution` plan preview format: with prepared templates + Pydantic validation, should the plan show the template + validated param dict (clearer for the user) or keep the fully-rendered SQL string (matches today)? — *Owner: Jesus Lara: template + validated (clearer for user)
- [x] `NavigatorToolkit.tool_prefix = ""` override is proposed to preserve current tool names. Should future Navigator-adjacent toolkits follow this convention, or should we introduce a `navigator_` prefix as part of a broader tool-namespace audit? — *Owner: Jesus Lara*: tool prefix = nav
- [x] LRU size for `_build_pydantic_model`: default proposed `maxsize=256`. Is that enough across typical deployments, or should we set `maxsize=None` given the finite table shapes? — *Owner: Jesus Lara*: maxsize=None
- [x] Should `PostgresToolkit.transaction()` support nested transactions (savepoints)? Out of scope for v1 (Non-Goals), but confirm. — *Owner: Jesus Lara*: Out of scope

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (one worktree for the whole feature).
- **Modules internally**:
  - Modules 1 (QueryValidator), 2 (TableMetadata), 3 + 4 (_crud.py pure
    helpers) *could* run as parallel worktrees — each touches disjoint
    files. However, Modules 3 and 4 live in the same new file, so they
    serialize. Module 5 (`PostgresToolkit` wiring) depends on 1+2+3+4.
    Module 6 (`NavigatorToolkit` refactor) depends on 5.
  - Splitting into parallel worktrees adds coordination cost that
    exceeds the parallelism benefit for a medium-sized feature: the
    tests for Modules 3–5 depend on Modules 1+2 being merged, and
    Module 6 needs all prior modules stable.
  - Recommended execution: `sdd-worker` walking tasks 1→2→3→4→5→6→7→8
    sequentially in one worktree. Each task commits independently;
    rollback of any one task is clean.
- **Cross-feature dependencies**:
  - **None blocking.** FEAT-105 (`databasetoolkit-clash`) is concurrent
    but touches a disjoint module tree (`parrot.tools.databasequery.*`
    vs our `parrot.bots.database.*`). No merge conflict expected.
  - No other active spec modifies `query_validator.py`, `sql.py`,
    `postgres.py`, `models.py`, or `parrot_tools/navigator/toolkit.py`
    (verified by `ls sdd/specs/ sdd/tasks/active/` at spec time).
- **Worktree naming**: `feat-106-navigatortoolkit-postgrestoolkit-interaction`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-17 | Jesus Lara | Initial draft — carried forward from brainstorm (Option B). |
