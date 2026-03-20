# FEAT-032: Database Schema Tools — Completion & Hardening

**Feature ID**: FEAT-032
**Date**: 2026-03-08
**Status**: approved
**Priority**: high
**Author**: claude-sonnet-4-6

---

## Problem Statement

`parrot/tools/database` contains partially implemented schema-introspection tools for PostgreSQL
(`PgSchemaSearchTool`) and BigQuery (`BQSchemaSearchTool`). Three areas are incomplete:

1. **Package exports**: `parrot/tools/database/__init__.py` is empty — neither tool is importable
   from the sub-package.
2. **Vector-store tier of the cache**: `SchemaMetadataCache` defines a two-tier architecture
   (LRU + vector store) but all three vector-store methods (`_search_vector_store`,
   `_store_in_vector_store`, `_convert_vector_results`) are stubs that do nothing.  Both
   `FAISSStore` (in-memory) and `PgVectorStore` (persistent) exist in `parrot/stores/` but are not
   wired up.
3. **Credential handling**: `AbstractSchemaManagerTool` always uses the global `asyncpg_sqlalchemy_url`
   constant.  No fallback credential logic mirrors the `DatabaseQueryTool._get_default_credentials`
   pattern.  BigQuery additionally has no dedicated engine-creation path.

---

## Goals

- Export `PgSchemaSearchTool` and `BQSchemaSearchTool` from `parrot/tools/database/__init__.py`.
- Complete the vector-store tier of `SchemaMetadataCache`:
  - Default (no config): in-memory `FAISSStore`.
  - Optional: caller passes a `PgVectorStore` instance for persistent semantic search.
  - Implement real `_store_in_vector_store`, `_search_vector_store`, `_convert_vector_results`.
- Add `_get_default_credentials` to `AbstractSchemaManagerTool` following the
  `DatabaseQueryTool` pattern:
  - When no `dsn` or `engine` is provided, build credentials from navconfig env vars.
  - For PostgreSQL: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`,
    `POSTGRES_PASSWORD`.
  - For BigQuery: `BIGQUERY_CREDENTIALS_PATH`, `BIGQUERY_PROJECT_ID`.
- Fix `BQSchemaSearchTool` engine creation to use a proper BigQuery DSN
  (`bigquery://<project>/<dataset>`) with google-auth credentials, not a raw SQLAlchemy
  asyncpg connection.

---

## Non-Goals

- Adding new database backends beyond PostgreSQL and BigQuery.
- Implementing query execution (that is `DatabaseQueryTool`'s responsibility).
- Distributed / persistent LRU caching (Redis, Memcached).
- Changing `SchemaMetadata` or `TableMetadata` data models.
- Altering `AbstractStore` interface.

---

## Architectural Design

### Module Layout (unchanged)

```
parrot/tools/database/
├── __init__.py        # TASK-233: add exports
├── abstract.py        # TASK-234: add _get_default_credentials + _build_engine_from_creds
├── cache.py           # TASK-235: complete vector-store tier
├── bq.py              # TASK-236: fix engine creation + implement _search_in_database
├── models.py          # unchanged
└── pg.py              # unchanged
```

### Credential Resolution (AbstractSchemaManagerTool)

```
__init__(dsn=None, engine=None, credentials=None, database_type="postgresql")
    │
    ├─ engine provided? ──────────────────────────────► use it
    ├─ dsn provided? ─────────────────────────────────► build engine from dsn
    └─ neither? ──────────────────────────────────────► _get_default_credentials(database_type)
                                                            └─ build engine from creds
```

`_get_default_credentials(database_type: str) -> dict` reads from `navconfig.config` with
`os.environ` fallback, identical in structure to `DatabaseQueryTool._get_default_credentials`.

### Vector-Store Tier Completion

`SchemaMetadataCache.__init__` accepts `vector_store: Optional[AbstractStore]`:

| `vector_store` value | Behaviour |
|---|---|
| `None` (default) | Auto-create `FAISSStore` (in-memory, no persistence) |
| `AbstractStore` instance | Use as-is (e.g. `PgVectorStore`) |

The three stub methods become real:

- **`_store_in_vector_store(metadata)`** — converts `TableMetadata.to_yaml_context()` into a
  `Document`-like dict and calls `vector_store.add_documents(...)` inside an async context manager.
- **`_search_vector_store(schema_name, table_name)`** — calls
  `vector_store.similarity_search(f"{schema_name}.{table_name}", k=1, ...)`, returns first match
  converted to `TableMetadata` or `None`.
- **`_convert_vector_results(results)`** — parses YAML content stored by `_store_in_vector_store`
  back into `TableMetadata` objects.

`SchemaMetadataCache.search_similar_tables` uses `vector_store.similarity_search` with a metadata
filter `{"schema_name": {"$in": schema_names}}` when vector store is enabled, with graceful
fallback to `_search_cache_only`.

### BigQuery Engine Fix (`BQSchemaSearchTool`)

BigQuery does not use asyncpg.  A dedicated `_get_engine` override builds a synchronous
`sqlalchemy-bigquery` engine (`bigquery://<project>/<dataset>`) and wraps it with
`AsyncAdaptedQueuePool`.  Credentials are loaded from the service-account JSON at
`BIGQUERY_CREDENTIALS_PATH`.

---

## Affected Files

| File | Action | Task |
|---|---|---|
| `parrot/tools/database/__init__.py` | MODIFY — add exports | TASK-233 |
| `parrot/tools/database/abstract.py` | MODIFY — credential resolution | TASK-234 |
| `parrot/tools/database/cache.py` | MODIFY — complete vector-store tier | TASK-235 |
| `parrot/tools/database/bq.py` | MODIFY — BQ engine + `_search_in_database` | TASK-236 |

---

## Environment Variables

| Variable | Used by | Default |
|---|---|---|
| `POSTGRES_HOST` | PG credential fallback | `localhost` |
| `POSTGRES_PORT` | PG credential fallback | `5432` |
| `POSTGRES_DB` | PG credential fallback | `postgres` |
| `POSTGRES_USER` | PG credential fallback | `postgres` |
| `POSTGRES_PASSWORD` | PG credential fallback | (required) |
| `BIGQUERY_CREDENTIALS_PATH` | BQ engine creation | (required for BQ) |
| `BIGQUERY_PROJECT_ID` | BQ engine creation | (required for BQ) |

---

## Acceptance Criteria

- [ ] `from parrot.tools.database import PgSchemaSearchTool, BQSchemaSearchTool` succeeds.
- [ ] `SchemaMetadataCache()` (no args) auto-creates `FAISSStore` internally; vector tier is
      active without caller configuration.
- [ ] `SchemaMetadataCache(vector_store=pg_store)` uses `PgVectorStore` for similarity search.
- [ ] `_store_in_vector_store` stores YAML-serialised `TableMetadata` in the vector store.
- [ ] `_search_vector_store(schema, table)` returns a `TableMetadata` or `None` (not always
      `None` as today).
- [ ] `_convert_vector_results(results)` returns a non-empty list when vector results contain
      valid YAML.
- [ ] `AbstractSchemaManagerTool(allowed_schemas=["public"])` (no `dsn`, no `engine`) builds
      an engine from navconfig env vars without raising.
- [ ] `BQSchemaSearchTool` creates a BigQuery-compatible engine when `database_type="bigquery"`
      and credentials path is configured.
- [ ] `BQSchemaSearchTool._search_in_database(...)` is implemented (mirrors
      `PgSchemaSearchTool._search_in_database`).
- [ ] `ruff check parrot/tools/database/` passes with no errors.
- [ ] Existing `PgSchemaSearchTool` search behaviour is unchanged.

---

## Test Specification

Tests live in `tests/tools/database/`.

### `test_init_exports.py`
- Import `PgSchemaSearchTool`, `BQSchemaSearchTool` from `parrot.tools.database`.

### `test_cache_vector_tier.py`
- `SchemaMetadataCache()` auto-creates FAISSStore.
- `store_table_metadata` calls `_store_in_vector_store` when vector store present.
- `_convert_vector_results` round-trips a stored `TableMetadata` back correctly.
- `search_similar_tables` falls back to `_search_cache_only` on vector store error.

### `test_abstract_credentials.py`
- `_get_default_credentials("postgresql")` reads env vars correctly.
- `_get_default_credentials("bigquery")` reads `BIGQUERY_CREDENTIALS_PATH` / `BIGQUERY_PROJECT_ID`.
- `AbstractSchemaManagerTool` with no `dsn`/`engine` calls `_get_default_credentials`.

### `test_bq_tool.py`
- `BQSchemaSearchTool._get_engine` returns an engine with `bigquery://` dialect.
- `BQSchemaSearchTool._search_in_database` returns `List[TableMetadata]` (mock BQ session).

---

## Dependencies

| Package | Already present | Notes |
|---|---|---|
| `cachetools` | yes | TTLCache — unchanged |
| `faiss-cpu` | yes (`FAISSStore` exists) | In-memory vector tier |
| `sqlalchemy-bigquery` | check | Required for BQ engine; add if missing |
| `google-auth` | check | Required for BQ service-account credentials |

---

## Implementation Notes

- Do NOT use `rm -rf` or destructive filesystem operations.
- In `_convert_vector_results`, parse the `content` field of each result with `yaml.safe_load`;
  reconstruct a `TableMetadata` from the parsed dict.  Missing fields default to empty list / None.
- The `FAISSStore` auto-creation in `SchemaMetadataCache` must be lazy (only when first needed) or
  guarded with `try/except ImportError` to avoid breaking environments without `faiss-cpu`.
- `_store_in_vector_store` must open the store as an async context manager
  (`async with self.vector_store as vs: await vs.add_documents(...)`) — do not call raw methods
  without a connection context.
- `BQSchemaSearchTool._search_in_database` should query `INFORMATION_SCHEMA.TABLES` filtered by
  `table_schema IN UNNEST(...)` and call `analyze_table` for each row, mirroring the PG
  implementation.
- Keep all existing public method signatures unchanged to preserve caller compatibility.
