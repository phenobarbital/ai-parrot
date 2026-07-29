---
type: Wiki Overview
title: 'Feature Specification: Database Toolkit Cache Contract & Tool Semantics'
id: doc:sdd-specs-database-toolkit-cache-contract-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: (`db_search_schema`, `db_generate_query`, `db_validate_query`). In production,
relates_to:
- concept: mod:parrot.bots.database.agent
  rel: mentions
- concept: mod:parrot.bots.database.cache
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.prompts
  rel: mentions
- concept: mod:parrot.bots.database.retries
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.base
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.postgres
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.sql
  rel: mentions
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Database Toolkit Cache Contract & Tool Semantics

**Feature ID**: FEAT-178
**Date**: 2026-05-15
**Author**: jfrruffato@trocglobal.com
**Status**: approved
**Target version**: TBD

---

## 1. Motivation & Business Requirements

### Problem Statement

`DatabaseAgent` (FEAT-164) ships with a `CachePartition` and three LLM tools
(`db_search_schema`, `db_generate_query`, `db_validate_query`). In production,
the `sql_analyst` consumer (navigator-plugins) pre-warms the cache with up to
~5k `TableMetadata` stubs sourced from the frontend's editor schema tree, then
relies on these tools to drive natural-language → SQL generation.

Observed sessions reveal that the **cache silently returns incomplete data as
if it were authoritative**, causing two distinct failure modes:

1. **Stub-disguised-as-metadata.** `cache_partition.get_table_metadata(schema,
   table)` returns a `TableMetadata` with `columns=[]` when only the table
   name was pre-warmed. `SQLToolkit.generate_query` (`toolkits/sql.py:159-165`)
   accepts the empty stub, renders YAML with `columns: []`, and the LLM
   declines to generate SQL ("no tengo información sobre las columnas").
   **There is no DB fallback** when `target_tables` is provided.

2. **Early-return on partial cache hits.** `SQLToolkit.search_schema`
   (`toolkits/sql.py:125-132`) returns the first cache hit list without
   exhausting the database. When the cache holds 3 alphabetically-earlier
   matches for `"store"` (e.g., `altice.store_inventory`, `altice.store_groups`),
   `pokemon.stores` — which the user actually wanted — is never returned even
   though it exists in `information_schema` and would be found by the DB
   fallback.

A third symptom — `search_schema(search_term="alaska")` returning `[]` despite
the user asking about Alaska stores — is **correct behaviour by current
contract**: `search_schema` matches identifiers (table/column/comment names),
not data values. But the agent's system prompt does not communicate this
contract, so the LLM repeatedly misuses the tool on row-value strings.

A fourth defect — `_score_against_cache` (`cache.py:357-365`) returns matches
in **iteration order** of `schema_cache.items()` and truncates at `limit`,
not by relevance score — means even if `pokemon.stores` scores higher than
`altice.store_inventory`, the alphabetically-earlier table wins.

The root cause across all four failures is **type-level ambiguity**:
`TableMetadata` represents three semantically distinct states (name-only,
name+columns, full introspection) with a single struct, and the cache API
does not let consumers express what level of completeness they need.
Downstream tools therefore cannot reason about freshness or sufficiency.

### Goals

- A consumer of `CachePartition` can ask for metadata at a stated completeness
  level and receive `None` instead of partial data when that level is not met.
- Every `TableMetadata` instance carries explicit `completeness`, `loaded_at`,
  and `source` fields. The YAML rendered for the LLM surfaces this state.
- `db_generate_query` is repurposed: instead of trusting cache stubs, it
  internally calls `db_describe_table` for each target and emits a templated
  SELECT skeleton with real column names.
- `db_search_schema` keeps its name but its behaviour is fixed: merges cache
  hits with DB hits up to `limit`, sorts by relevance score, no early-return.
- A new `db_describe_table(schema, table)` tool guarantees `Completeness.FULL`
  output by falling through to DB introspection on cache stubs.
- LLM system prompt explicitly documents the tool workflow and that
  `db_search_schema` searches *identifiers*, not data values.
- Cache entries have configurable per-completeness TTL; stale entries are
  not served.
- Concurrent misses for the same `(schema, table)` coalesce into a single
  DB introspection.
- PostgresToolkit introspection queries migrate from `information_schema`
  to `pg_catalog` (faster, richer, surfaces real PG metadata).
- Frontend pre-warm block format gains explicit completeness tags
  (`table[NAME_ONLY]`, `table[WITH_COLUMNS](col:type;...)`).

### Non-Goals (explicitly out of scope)

- Vector / semantic search redesign. The vector path is preserved and gets
  post-hoc completeness filtering, but its scoring/embedding model is not
  changed.
- Schema-version detection via `pg_class.relfilenode` or PG event triggers.
  TTL is the only invalidation mechanism in this iteration. (`pg_catalog`
  migration unlocks this for a follow-up.)
- Multi-node distributed cache invalidation.
- Per-user cache partitioning. Cache namespace remains keyed by
  `(database_type, primary_schema)` (e.g., `postgresql_public`).
  Permission-aware partitioning is deferred to a follow-up.
- Reworking BigQuery / Elastic / InfluxDB / DocumentDB toolkits. Scope is
  `SQLToolkit` + `PostgresToolkit`. Other SQL dialects benefit by virtue of
  inheriting from `SQLToolkit` but their specific behaviour is not validated.
- The `gemini-3-flash-preview` vs `gemini-2.5-flash` model-override defect
  observed in `sql_analyst` sessions is unrelated to the cache contract and
  belongs in a separate spec.
- Introducing new LLM tools beyond `db_describe_table`. We do not add
  `db_list_tables` or `db_search_tables` — `db_search_schema` covers
  discovery once fixed.

---

## 2. Architectural Design

### Overview

Introduce a `Completeness` enum and elevate it to a first-class field on
`TableMetadata`. Rework the cache API so every read declares the minimum
completeness the caller needs; the cache returns `None` when that level is
not met, forcing a DB fallback at the toolkit layer.

**Tool surface (Q1 — rename in-place; Q4 — repurpose):**
- `db_search_schema` keeps its name and signature but is fixed to merge
  cache + DB, sort by relevance, and no longer early-return on partial
  cache hits. Return type still `List[TableMetadata]` at `NAME_ONLY` or
  better — callers are not promised columns.
- `db_describe_table(schema, table)` is **new**. Guarantees
  `Completeness.FULL` — promotes cache stubs by calling DB introspection,
  coalesces concurrent identical calls.
- `db_generate_query(natural_language, target_tables?, query_type)` is
  **repurposed**: instead of pulling YAML from cache, it calls
  `db_describe_table` internally for each entry in `target_tables` and
  returns a templated `SELECT` skeleton with real column names. If
  `target_tables` is empty, it calls `db_search_schema` first to discover
  candidates, then `describe_table` on the top hits. The LLM still drives
  final SQL — `db_generate_query` is a scaffold helper, not the SQL
  author. `target_tables` becomes a required argument once the new
  workflow ships (deprecation pass first).
- `db_validate_query(sql)` unchanged.

**Frontend wire format (Q3 — explicit tags):** the pre-warm block emitted
by navigator-plugins (`docs/sql.py:_consume_schema_block` consumer) gains
explicit completeness tags. The block goes from:

```
- pokemon: stores, products(id:int;name:varchar)
```

to:

```
- pokemon: stores[NAME_ONLY], products[WITH_COLUMNS](id:int;name:varchar)
```

The parser in navigator-plugins is updated accordingly (Module 9), and the
frontend executor page is updated to emit the tagged form (Module 10).

**PostgresToolkit introspection (Q7 — migrate to `pg_catalog`):** the
`_get_*` query hooks in `toolkits/postgres.py` are rewritten against
`pg_catalog`. This is faster (native PG indexes), richer (system OIDs,
relfilenode for future DDL detection, partition info), and resolves a
class of inconsistencies between `information_schema` views and reality.

**Concurrency-safe DB introspection** is added via a per-toolkit
`_inflight: Dict[(str,str), asyncio.Future]` map plus a lock, so
simultaneous `describe_table` calls for the same key coalesce.

**System prompt:** a new `SCHEMA_TOOL_USAGE_LAYER` documents the workflow:
list/search returns names only; describe returns full structure; never
generate SQL referencing a table that has not been described.

### Component Diagram

```
LLM
 │
 ├── db_search_schema(term, schema?)    ─┐
 ├── db_describe_table(schema, table)   ─┤
 ├── db_generate_query(...)             ─┤
 └── db_validate_query(sql)             ─┘
        │
        ▼
SQLToolkit (fixed + extended)
 │
 ├── search_schema()         ─ merges cache(by score) ∪ DB, no early-return
 ├── describe_table()        ─ NEW; guarantees FULL; coalesces concurrent calls
 ├── generate_query()        ─ REPURPOSED; calls describe_table internally
 │                             and emits a SELECT skeleton with real columns
 │
 ▼
CachePartition (new API)
 ├── get(schema, table, required=…, max_age=…) → TableMetadata | None
 ├── list(schemas, completeness_min=…, max_age=…, limit=…) → List
 ├── search(schemas, term, completeness_min=…, max_age=…, limit=…) → List
 └── store_table_metadata(meta)   ← respects per-completeness TTL
        │
        ├── LRU TTLCache (per-completeness TTL)
        ├── Redis (per-completeness TTL)
        └── Vector store ─ candidates filtered post-hoc by completeness
        
PostgresToolkit hooks (migrated to pg_catalog)
 ├── _get_information_schema_query     ─ NOW pg_catalog-based, name kept for API stability
 ├── _get_columns_query                 ─ NOW pg_catalog
 ├── _get_primary_keys_query            ─ NOW pg_catalog
 ├── _get_unique_constraints_query      ─ NOW pg_catalog
 ├── _get_indexes_query                 ─ NEW, pg_catalog
 └── _get_foreign_keys_query            ─ NEW, pg_catalog

Frontend pre-warm wire format
 - schema: name[NAME_ONLY], named_cols[WITH_COLUMNS](col:type;...), …
            └── navigator-plugins parser sets meta.completeness explicitly
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.bots.database.models.TableMetadata` | extend | Add `completeness`, `loaded_at`, `source` fields with backwards-compatible defaults |
| `parrot.bots.database.cache.CachePartition` | rework API | `get`/`list`/`search`/`store` accept and respect completeness levels |
| `parrot.bots.database.cache.CachePartitionConfig` | extend | Add `ttl_by_completeness: Dict[Completeness, int]` |
| `parrot.bots.database.toolkits.sql.SQLToolkit` | fix + extend | `search_schema` fixed; `describe_table` added; `generate_query` repurposed |
| `parrot.bots.database.toolkits.postgres.PostgresToolkit` | rewrite hooks | All `_get_*` queries migrate to `pg_catalog`; add `_get_indexes_query`, `_get_foreign_keys_query` |
| `parrot.bots.database.prompts` | add layer | New `SCHEMA_TOOL_USAGE_LAYER` |
| `parrot.bots.database.agent.DatabaseAgent` | minor | Forward `cache_ttl_by_completeness=…` kwarg into `CachePartitionConfig` |
| navigator-plugins `docs/sql.py` | downstream consumer | Parser updated for `[NAME_ONLY]`/`[WITH_COLUMNS]` tags; sets `completeness` per entry |
| navigator-plugins `executor/+page.svelte` | downstream consumer | Frontend block emits explicit tags |

### Data Models

```python
# parrot/bots/database/models.py

from enum import IntEnum
from datetime import datetime
from typing import Literal, Optional


class Completeness(IntEnum):
    """Level of metadata loaded for a table.

    Higher values strictly subsume lower ones. Consumers declare the
    minimum they need; the cache enforces the contract.
    """
    NAME_ONLY = 1     # exists in this schema, nothing else known
    WITH_COLUMNS = 2  # + column names and types
    FULL = 3          # + primary keys + unique constraints + indexes + comments + FKs


MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "unknown"]


@dataclass
class TableMetadata:
    schema: str
    tablename: str
    table_type: str
    full_name: str
    # NEW (defaults preserve backwards-compat for existing call sites):
    completeness: Completeness = Completeness.FULL
    loaded_at: datetime = field(default_factory=datetime.utcnow)
    source: MetadataSource = "unknown"
    # ... existing fields unchanged
    comment: Optional[str] = None
    columns: List[Dict[str, Any]] = field(default_factory=list)
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[Dict[str, Any]] = field(default_factory=list)
    indexes: List[Dict[str, Any]] = field(default_factory=list)
    row_count: Optional[int] = None
    sample_data: List[Dict[str, Any]] = field(default_factory=list)
    unique_constraints: List[List[str]] = field(default_factory=list)
    last_accessed: Optional[datetime] = None
    access_frequency: int = 0
    avg_query_time: Optional[float] = None

    def satisfies(self, required: Completeness) -> bool:
        return self.completeness >= required
```

### New / Changed Public Interfaces

```python
# parrot/bots/database/cache.py

class CachePartitionConfig(BaseModel):
    namespace: str
    lru_maxsize: int = 500
    lru_ttl: int = 1800
    redis_ttl: int = 3600
    # NEW: per-completeness TTL caps (used as the min between this and
    # the tier-level TTL). Defaults: 24h NAME_ONLY, 6h WITH_COLUMNS, 1h FULL.
    ttl_by_completeness: Dict[Completeness, int] = Field(
        default_factory=lambda: {
            Completeness.NAME_ONLY: 86400,
            Completeness.WITH_COLUMNS: 21600,
            Completeness.FULL: 3600,
        }
    )


class CachePartition:
    async def get(
        self,
        schema_name: str,
        table_name: str,
        *,
        required: Completeness = Completeness.NAME_ONLY,
        max_age: Optional[timedelta] = None,
    ) -> Optional[TableMetadata]:
        """Return metadata only if entry exists, is fresher than ``max_age``
        (default: ``ttl_by_completeness[entry.completeness]``), and satisfies
        ``required``. Returns ``None`` otherwise. The caller decides whether
        to fetch from DB on ``None``."""

    async def list(
        self,
        schema_names: List[str],
        *,
        completeness_min: Completeness = Completeness.NAME_ONLY,
        max_age: Optional[timedelta] = None,
        limit: Optional[int] = None,
    ) -> List[TableMetadata]:
        """Enumerate cached tables in the given schemas at or above the
        minimum completeness, fresher than ``max_age``."""

    async def search(
        self,
        schema_names: List[str],
        search_term: str,
        *,
        completeness_min: Completeness = Completeness.NAME_ONLY,
        max_age: Optional[timedelta] = None,
        limit: int = 20,
    ) -> List[TableMetadata]:
        """Cache-side search. Returns up to ``limit`` results sorted by
        relevance score descending (exact > substring > column match).
        Vector path (when enabled) is consulted first; vector candidates
        are filtered post-hoc against ``completeness_min`` and ``max_age``,
        then merged with structural cache results.
        Does NOT do DB fallback — that is the toolkit's responsibility."""

    # Backwards-compat:
    #   get_table_metadata(schema, table) → calls get(...) with defaults
    #   search_similar_tables(schemas, query, limit) → calls search(...)
    # Both keep their existing signatures; both emit DeprecationWarning


# parrot/bots/database/toolkits/sql.py

class SQLToolkit(DatabaseToolkit):

    # SAME signature as today — behaviour fixed.
    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 20,
    ) -> List[TableMetadata]:
        """Find tables whose NAME, COLUMN NAME, or COMMENT matches ``search_term``.

        Searches **identifiers, not data values** ("alaska" as a state value
        is not findable here — search for "store" then describe).

        Implementation: cache-side search via ``cache_partition.search`` plus
        DB lookup via ``_search_in_database``, merged and deduplicated, sorted
        by relevance score, truncated to ``limit``. Concurrent identical
        calls for the same ``(term, schema)`` coalesce.
        """

    # NEW.
    async def describe_table(
        self,
        schema: str,
        table: str,
    ) -> Optional[TableMetadata]:
        """Return full table introspection (columns, PKs, FKs, indexes,
        unique constraints, comment). Cache hit at ``Completeness.FULL``
        is served directly; lower completeness or miss triggers DB
        introspection, populates cache at ``Completeness.FULL``, and
        returns the result. Concurrent calls for the same ``(schema,
        table)`` coalesce via an inflight-future map."""

    # REPURPOSED — same signature, new internals.
    async def generate_query(
        self,
        natural_language: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "SELECT",
    ) -> str:
        """Build a SQL skeleton grounded in real columns.

        1. If ``target_tables`` is empty: call ``search_schema(natural_language,
           limit=5)`` to discover candidates.
        2. For every (resolved) target table: call ``describe_table(schema,
           table)``. This GUARANTEES the columns are real (DB-introspected
           when cache only had a stub).
        3. Render a templated ``SELECT`` skeleton listing the actual column
           names plus a stub ``WHERE`` / ``JOIN`` based on shared columns,
           along with a YAML block of full metadata for each table.

        The LLM still authors the final SQL — this method ensures the LLM
        sees real columns, not empty stubs.
        """
```

### Tool Surface Change

| Tool | Before (FEAT-164) | After (FEAT-178) |
|---|---|---|
| `db_search_schema` | cache early-return; no score sort | cache+DB merged; score-sorted; documented as identifier search |
| `db_generate_query` | cache-only YAML; silently returns empty `columns: []` | calls `db_describe_table` per target; emits real-column SELECT skeleton |
| `db_describe_table` | *(does not exist)* | NEW; guarantees `Completeness.FULL`; coalesces concurrent calls |
| `db_validate_query` | unchanged | unchanged |

---

## 3. Module Breakdown

### Module 1: Completeness model & metadata fields

- **Path**: `packages/ai-parrot/src/parrot/bots/database/models.py`
- **Responsibility**: Add `Completeness` enum, `MetadataSource` literal, and
  three new fields on `TableMetadata` (`completeness`, `loaded_at`, `source`).
  Add `TableMetadata.satisfies()`. Update `to_yaml_context()` to emit
  `completeness` and `loaded_at` fields and a `_warning` line for non-FULL
  entries (e.g., *"NAME_ONLY stub — call db_describe_table to load columns
  before generating SQL."*).
- **Depends on**: nothing (foundation)

### Module 2: CachePartition API rework

- **Path**: `packages/ai-parrot/src/parrot/bots/database/cache.py`
- **Responsibility**: Implement new `get`/`list`/`search`/`store` signatures
  with completeness + max_age gating. Update `_calculate_relevance_score`
  and `_score_against_cache` to **sort by score descending** before
  truncating. Extend `CachePartitionConfig` with `ttl_by_completeness`.
  Vector path (`search_similar_tables`) keeps its embedding query but
  filters results post-hoc by `completeness_min` and `max_age` (Q5).
  Add backwards-compat aliases `get_table_metadata` and
  `search_similar_tables` that delegate to the new API and emit
  `DeprecationWarning`.
- **Depends on**: Module 1

### Module 3: Concurrency coalescing for DB introspection

- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`
- **Responsibility**: Add `_inflight: Dict[Tuple[str, str], asyncio.Future[Optional[TableMetadata]]]`
  and an `_inflight_lock: asyncio.Lock` on `SQLToolkit`. Introduce
  `_introspect_table_full(schema, table)` which checks/sets/clears the
  future under the lock, with the actual DB work happening outside.
  Used by `describe_table` and by `search_schema` when promoting a cache
  hit from `NAME_ONLY` to `FULL` on demand.
- **Depends on**: Module 1

### Module 4: SQLToolkit tool methods (fix + extend + repurpose)

- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`
- **Responsibility**:
  - Fix `search_schema`: no early-return; merge `cache_partition.search(...)`
    with `_search_in_database(...)` results; deduplicate by `(schema,
    tablename)`; results sorted by score; results are at
    `Completeness.NAME_ONLY` minimum (cache hits may be higher).
  - Add `describe_table`: cache `get(required=FULL)` → if `None`,
    `_introspect_table_full` → store at `FULL` → return.
  - Repurpose `generate_query`: discover (if no `target_tables`) via
    `search_schema`, then `describe_table` over every target, then render
    a templated SELECT skeleton with the real columns. Returns a string
    formatted for LLM consumption (the YAML block + a `-- TODO: refine`
    SQL skeleton).
  - Update `exclude_tools` to hide new internal helpers.
- **Depends on**: Modules 1, 2, 3

### Module 5: PostgresToolkit pg_catalog migration

- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py`
- **Responsibility**: Rewrite the introspection hooks against `pg_catalog`:
  - `_get_information_schema_query` → uses `pg_class` + `pg_namespace`
    directly; name kept for API stability (does not break overrides);
    bumps `LIMIT` from hardcoded 20 to caller-provided `limit`.
  - `_get_columns_query` → uses `pg_attribute` + `pg_type` + `pg_attrdef`
    for defaults and `col_description()`.
  - `_get_primary_keys_query` → uses `pg_constraint` `contype = 'p'`.
  - `_get_unique_constraints_query` → uses `pg_constraint` `contype = 'u'`.
  - `_get_indexes_query` (NEW) → uses `pg_index` + `pg_class`.
  - `_get_foreign_keys_query` (NEW) → uses `pg_constraint` `contype = 'f'`.
  - All queries set `meta.source = "pg_catalog"` and `meta.completeness = FULL`
    when used by `_build_table_metadata` / `_introspect_table_full`.
- **Depends on**: Module 1 (for source/completeness fields)

### Module 6: Prompt layer for tool workflow

- **Path**: `packages/ai-parrot/src/parrot/bots/database/prompts.py`
- **Responsibility**: Add `SCHEMA_TOOL_USAGE_LAYER` describing the workflow
  (search → describe → generate) and explicitly stating that
  `db_search_schema` searches identifiers not data values. Wire into
  `_build_database_prompt_builder()`. The layer is unconditional (no
  `condition=...`) — it always renders.
- **Depends on**: Module 4

### Module 7: Tests

- **Path**: `packages/ai-parrot/tests/bots/database/`
- **Responsibility**: New unit tests per §4. Integration tests using the
  existing test Postgres (`packages/ai-parrot/tests/conftest.py`) that
  reproduce the `pokemon.stores` and `networkninja.forms` JOIN failures
  and assert they now succeed. Fixture data is seeded explicitly (the
  test DB does not have these schemas by default).
- **Depends on**: Modules 1–6

### Module 8: navigator-plugins parser update (downstream — tagged tracking)

- **Path**: `navigator-plugins/docs/sql.py`
- **Responsibility**: Update `_TABLE_SPEC_RE` and `_parse_table_specs` to
  parse the new `table[NAME_ONLY]` / `table[WITH_COLUMNS](col:type;...)`
  format. Construct `TableMetadata` with `completeness` set per the tag
  and `source="frontend"`. Keep legacy parsing as a fallback for one
  release so old frontend builds continue to work.
- **Depends on**: Module 1

### Module 9: navigator-plugins frontend emitter (downstream — tagged tracking)

- **Path**: `navigator-plugins/src/routes/executor/+page.svelte` (or
  wherever the schema block is assembled — confirm via grep)
- **Responsibility**: Emit the new `[NAME_ONLY]` / `[WITH_COLUMNS]` tags
  when assembling the pre-warm block. The frontend already knows the
  completeness — it's whether the schema-tree node has been expanded.
- **Depends on**: Module 8 (parser must accept new format before emitter
  starts sending it)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|

…(truncated)…
