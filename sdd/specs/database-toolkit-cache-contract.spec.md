---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Database Toolkit Cache Contract & Tool Semantics

**Feature ID**: FEAT-177
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

| Tool | Before (FEAT-164) | After (FEAT-177) |
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
| `test_completeness_ordering` | 1 | `NAME_ONLY < WITH_COLUMNS < FULL` and `satisfies()` returns correctly |
| `test_table_metadata_default_completeness` | 1 | Default is `FULL` (backwards-compat with existing call sites that don't set it) |
| `test_to_yaml_emits_warning_for_stubs` | 1 | YAML for `NAME_ONLY`/`WITH_COLUMNS` contains a `_warning` field telling the LLM to call describe |
| `test_cache_get_respects_required_level` | 2 | Stub with `NAME_ONLY` requested at `FULL` returns `None` |
| `test_cache_get_respects_max_age` | 2 | Entry older than `max_age` returns `None`; default `max_age` uses `ttl_by_completeness[entry.completeness]` |
| `test_cache_search_sorts_by_score` | 2 | Exact match `pokemon.stores` ranks above substring matches `altice.store_inventory` for term `"stores"` |
| `test_cache_search_completeness_min` | 2 | `completeness_min=WITH_COLUMNS` excludes name-only stubs |
| `test_cache_vector_results_filtered_post_hoc` | 2 | When vector path returns a stale or low-completeness candidate, it is dropped before merge |
| `test_cache_per_completeness_ttl` | 2 | NAME_ONLY entry survives past 1h (FULL TTL); FULL entry past 1h is evicted |
| `test_deprecation_warning_on_get_table_metadata` | 2 | Legacy `get_table_metadata` emits `DeprecationWarning` |
| `test_describe_table_coalesces_concurrent_calls` | 3 | Two parallel `describe_table` calls for same key issue one DB introspection |
| `test_describe_table_promotes_stub_to_full` | 4 | Cache has `NAME_ONLY` stub; `describe_table` triggers DB; cache after is `FULL` |
| `test_search_schema_merges_cache_and_db` | 4 | Cache holds 3 altice matches for `"store"`, DB has `pokemon.stores`. Result contains all 4 sorted by score |
| `test_search_schema_no_early_return` | 4 | Even when cache has hits for `"store"`, DB is still queried and results are merged |
| `test_search_schema_does_not_match_data_values` | 4 | `search_schema("alaska")` returns `[]` (no table/column named that) — documented contract |
| `test_generate_query_calls_describe_for_each_target` | 4 | `generate_query(target_tables=["a.x", "b.y"])` produces output containing real columns from both, never empty |
| `test_generate_query_emits_skeleton_with_real_columns` | 4 | Output contains a SELECT line listing actual column names from the introspected metadata |
| `test_pg_catalog_columns_query` | 5 | New `_get_columns_query` returns same shape as the old `information_schema` query for at least the canonical columns (name, type, nullable, default) |
| `test_pg_catalog_indexes_query` | 5 | NEW `_get_indexes_query` returns one row per index with column list and uniqueness flag |
| `test_pg_catalog_foreign_keys_query` | 5 | NEW `_get_foreign_keys_query` returns referencing/referenced tables, columns, and ON UPDATE/DELETE actions |
| `test_schema_tool_usage_layer_renders` | 6 | New prompt layer renders unconditionally in the system prompt and contains the workflow text |

### Integration Tests

| Test | Description |
|---|---|
| `test_pokemon_stores_alaska_regression` | Seed `pokemon.stores(store_id, store_name, state_code)`. Pre-warm only as `NAME_ONLY` stub. Agent flow `search_schema("store") → describe_table("pokemon", "stores") → generate SQL` produces a query referencing the real `state_code` column |
| `test_networkninja_join_regression` | Seed `networkninja.forms`, `networkninja.organizations` as `NAME_ONLY` stubs. Agent asked for a JOIN automatically describes both before generating SQL; result references real columns |
| `test_no_columns_yaml_does_not_silently_succeed` | `to_yaml_context()` on a `NAME_ONLY` stub always emits a `_warning` field — LLM cannot mistake it for full metadata |
| `test_frontend_pre_warm_completeness_tagging` | Parse a block with mixed `[NAME_ONLY]` and `[WITH_COLUMNS]` entries; cache entries have the correct `completeness` values |
| `test_pg_catalog_full_introspection_matches_information_schema` | For a seeded table, the new `pg_catalog`-based introspection returns at least the union of fields the old `information_schema` query returned |

### Test Data / Fixtures

```python
# packages/ai-parrot/tests/bots/database/conftest.py (extensions)

@pytest.fixture
def stub_metadata():
    """A NAME_ONLY TableMetadata stub for `pokemon.stores`."""
    return TableMetadata(
        schema="pokemon",
        tablename="stores",
        table_type="BASE TABLE",
        full_name='"pokemon"."stores"',
        completeness=Completeness.NAME_ONLY,
        source="frontend",
    )


@pytest.fixture
def full_metadata():
    """A FULL TableMetadata for `pokemon.stores`."""
    return TableMetadata(
        schema="pokemon",
        tablename="stores",
        table_type="BASE TABLE",
        full_name='"pokemon"."stores"',
        completeness=Completeness.FULL,
        source="pg_catalog",
        columns=[
            {"name": "store_id", "type": "integer", "nullable": False},
            {"name": "store_name", "type": "varchar", "nullable": True},
            {"name": "state_code", "type": "char(2)", "nullable": True},
        ],
        primary_keys=["store_id"],
    )


@pytest.fixture
async def seeded_pg(pg_pool):
    """Create pokemon.stores, networkninja.forms, networkninja.organizations
    in the test DB. Drop on teardown."""
    async with pg_pool.acquire() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS pokemon")
        await conn.execute("CREATE SCHEMA IF NOT EXISTS networkninja")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pokemon.stores (
                store_id    SERIAL PRIMARY KEY,
                store_name  VARCHAR(255),
                state_code  CHAR(2)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS networkninja.forms (
                form_id     SERIAL PRIMARY KEY,
                form_name   VARCHAR(255),
                org_id      INT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS networkninja.organizations (
                org_id          SERIAL PRIMARY KEY,
                organization    VARCHAR(255)
            )
        """)
    yield
    async with pg_pool.acquire() as conn:
        await conn.execute("DROP SCHEMA IF EXISTS pokemon CASCADE")
        await conn.execute("DROP SCHEMA IF EXISTS networkninja CASCADE")
```

---

## 5. Acceptance Criteria

- [ ] `TableMetadata` has `completeness`, `loaded_at`, and `source` fields
      with backwards-compatible defaults (default `Completeness.FULL`)
- [ ] All existing tests in `packages/ai-parrot/tests/bots/database/` still pass
- [ ] `CachePartition.get(required=Completeness.WITH_COLUMNS)` returns `None`
      for a `NAME_ONLY` stub
- [ ] `CachePartition.search` returns results sorted by relevance score
      (verified by `test_cache_search_sorts_by_score`)
- [ ] `CachePartitionConfig.ttl_by_completeness` is honored — verified by
      `test_cache_per_completeness_ttl`
- [ ] Vector store path applies `completeness_min` + `max_age` filtering
      post-hoc (verified by `test_cache_vector_results_filtered_post_hoc`)
- [ ] `SQLToolkit.search_schema` merges cache and DB results — never
      early-returns on partial cache hits (verified by
      `test_search_schema_merges_cache_and_db` and
      `test_search_schema_no_early_return`)
- [ ] `SQLToolkit.describe_table` guarantees `Completeness.FULL` output or
      returns `None` if the table truly does not exist
- [ ] `SQLToolkit.describe_table` coalesces concurrent identical calls into
      one DB introspection
- [ ] `SQLToolkit.generate_query` produces output containing real columns
      from `describe_table`, never empty `columns: []`
- [ ] All `PostgresToolkit._get_*` hooks use `pg_catalog`; new
      `_get_indexes_query` and `_get_foreign_keys_query` ship and are
      consumed by `describe_table`
- [ ] System prompt for `DatabaseAgent` includes the new
      `SCHEMA_TOOL_USAGE_LAYER`
- [ ] Integration regression tests for `pokemon.stores` and
      `networkninja.forms` failure modes pass
- [ ] `get_table_metadata` and `search_similar_tables` legacy aliases remain
      callable and emit `DeprecationWarning`
- [ ] No breaking changes to `DatabaseAgent` public constructor signature
      (new TTL config is optional)
- [ ] navigator-plugins parser accepts both legacy and tagged wire formats
      (Module 8). Frontend emitter updated to send tagged form (Module 9).
      Coordinated release order: ai-parrot → plugin parser → frontend
      emitter

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.**
> Implementation agents MUST consult these references and re-grep before
> assuming anything not listed here.

### Verified Imports

```python
# Stable foundation imports — confirmed working at HEAD on dev
from parrot.bots.database.models import TableMetadata, QueryResponse, SchemaMetadata
from parrot.bots.database.cache import CachePartition, CachePartitionConfig, CacheManager, SchemaMetadataCache
from parrot.bots.database.toolkits.base import DatabaseToolkit
from parrot.bots.database.toolkits.sql import SQLToolkit
from parrot.bots.database.toolkits.postgres import PostgresToolkit
from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.database.retries import QueryRetryConfig, RetryContext, SQLRetryHandler
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
```

### Existing Class Signatures (verified by reading source)

```python
# packages/ai-parrot/src/parrot/bots/database/models.py:116-141
@dataclass
class TableMetadata:
    schema: str                                          # line 119
    tablename: str                                       # line 120
    table_type: str                                      # line 121
    full_name: str                                       # line 122
    comment: Optional[str] = None                        # line 123
    columns: List[Dict[str, Any]] = field(...)           # line 124
    primary_keys: List[str] = field(...)                 # line 125
    foreign_keys: List[Dict[str, Any]] = field(...)      # line 126
    indexes: List[Dict[str, Any]] = field(...)           # line 127
    row_count: Optional[int] = None                      # line 128
    sample_data: List[Dict[str, Any]] = field(...)       # line 129
    unique_constraints: List[List[str]] = field(...)     # line 130
    last_accessed: Optional[datetime] = None             # line 134
    access_frequency: int = 0                            # line 135
    avg_query_time: Optional[float] = None               # line 136

    def __post_init__(self): ...                         # line 138
    def to_yaml_context(self) -> str: ...                # line 142
    def to_dict(self) -> Dict[str, Any]: ...             # line 170


# packages/ai-parrot/src/parrot/bots/database/cache.py:30-189
class CachePartitionConfig(BaseModel):                   # line 30 — extend with ttl_by_completeness

class CachePartition:                                    # line 43
    def __init__(self, namespace, lru_maxsize=500, lru_ttl=1800,
                 redis_ttl=3600, redis_pool=None, vector_store=None): ...  # line 55
    async def get_table_metadata(self, schema_name, table_name) -> Optional[TableMetadata]: ...  # line 95
    async def store_table_metadata(self, metadata: TableMetadata) -> None: ...  # line 138
    async def search_similar_tables(self, schema_names, query, limit=5) -> List[TableMetadata]: ...  # line 166
    def _calculate_relevance_score(self, table_name, table_meta, keywords) -> float: ...  # line 223
    def _search_cache_only(self, schema_names, query, limit) -> List[TableMetadata]: ...  # line 255
    def _score_against_cache(self, schema_names, keywords, seen, remaining) -> List[TableMetadata]: ...  # line 336


# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py:61-870
class SQLToolkit(DatabaseToolkit):
    exclude_tools: tuple[str, ...] = (...)                # line 70
    async def search_schema(self, search_term, schema_name=None, limit=10) -> List[TableMetadata]: ...   # line 106
    async def generate_query(self, natural_language, target_tables=None, query_type="SELECT") -> str: ...  # line 137
    async def execute_query(self, query, limit=1000, timeout=30): ...  # line 179
    async def explain_query(self, query: str) -> str: ...  # line 267
    async def validate_query(self, sql: str) -> Dict[str, Any]: ...  # line 404
    async def _warm_table_cache(self) -> None: ...        # line 471
    def _get_information_schema_query(...) -> tuple[str, tuple]: ...  # line 531
    def _get_columns_query(self, schema, table) -> tuple[str, tuple]: ...  # line 565
    def _get_primary_keys_query(self, schema, table) -> tuple[str, tuple]: ...  # line 584
    def _get_unique_constraints_query(...) -> tuple[str, tuple]: ...  # line 607
    async def _search_in_database(self, search_term, schema_name=None, limit=10) -> List[TableMetadata]: ...  # line 716
    async def _build_table_metadata(self, schema, table, table_type, comment=None) -> Optional[TableMetadata]: ...  # line 811


# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
# _get_information_schema_query at line 121 (uses information_schema.tables + pg_class for comment)
# Query body lines 135-153, LIMIT hard-coded to 20 at line 154
# _get_columns_query at line 156 (uses information_schema.columns)
# Both must be rewritten against pg_catalog (Module 5).


# packages/ai-parrot/src/parrot/bots/database/agent.py:85-200
class DatabaseAgent(BasicAgent):
    _default_temperature: float = 0.0                    # line 102
    max_tokens: int = 8192                                # line 103
    _prompt_builder: PromptBuilder = _build_database_prompt_builder()  # line 104
    def __init__(self, name="DatabaseAgent", toolkits=None, ...): ...  # line 106
    async def configure(self, app=None) -> None: ...     # line 134
    # Cache partition creation: agent.py:162-170 — pass CachePartitionConfig
    # with the new ttl_by_completeness field forwarded from kwargs.


# packages/ai-parrot/src/parrot/bots/database/prompts.py:15-86
DATABASE_CONTEXT_LAYER       # line 15
DATABASE_SAFETY_LAYER        # line 26
SCHEMA_GROUNDING_LAYER       # line 45 — conditional on schema_summary
DATABASE_INSTRUCTIONS_LAYER  # line 58
def _build_database_prompt_builder() -> PromptBuilder: ...  # line 76
```

### Defect Evidence (bugs this spec fixes)

```python
# toolkits/sql.py:125-132 — search_schema EARLY-RETURNS on any cache hit:
if self.cache_partition is not None:
    target_schemas = [schema_name] if schema_name else self.allowed_schemas
    cached = await self.cache_partition.search_similar_tables(
        target_schemas, search_term, limit=limit
    )
    if cached:
        return cached            # ← never consults DB to complete the picture
return await self._search_in_database(search_term, schema_name, limit)


# toolkits/sql.py:159-165 — generate_query with target_tables is CACHE-ONLY:
if target_tables and self.cache_partition:
    for table_name in target_tables:
        for schema in self.allowed_schemas:
            meta = await self.cache_partition.get_table_metadata(schema, table_name)
            if meta:
                context_parts.append(meta.to_yaml_context())
                break           # ← no fallback when meta.columns is []


# cache.py:357-365 — _score_against_cache returns in ITERATION ORDER, not by score:
for schema_name in schema_names:
    if schema_name not in self.schema_cache:
        continue
    all_objects = self.schema_cache[schema_name].get_all_objects()
    for table_name, table_meta in all_objects.items():
        key = (schema_name, table_name)
        if key in seen:
            continue
        score = self._calculate_relevance_score(table_name, table_meta, keywords)
        if score > 0:
            out.append(table_meta)
            if len(out) >= remaining:
                return out      # ← truncates to N hits, score irrelevant once limit reached


# models.py:142-168 — to_yaml_context emits `columns: []` with no signal:
data = {
    'table': self.full_name,
    'columns': [...]            # empty list when stub; no indication of stub-ness
    ...
}
return yaml.dump(data, ...)
```

### Integration Points

| New / Changed Component | Connects To | Via | Verified At |
|---|---|---|---|
| `Completeness` enum | `TableMetadata.completeness` | new field | new |
| `CachePartition.get(required=…)` | `SQLToolkit.describe_table` | method call | new |
| `SQLToolkit.search_schema` (fixed) | `cache_partition.search`, `_search_in_database` | merge | toolkits/sql.py:716 (DB path kept) |
| `SQLToolkit.describe_table` (new) | `_introspect_table_full` | direct call | new |
| `SQLToolkit.generate_query` (repurposed) | `describe_table`, `search_schema` | internal calls | new |
| `PostgresToolkit._get_*` | `_build_table_metadata` (kept) | replaced query bodies | postgres.py:121, 156; sql.py:584, 607 |
| `PostgresToolkit._get_indexes_query` (NEW) | `_introspect_table_full` | introspection query | new |
| `PostgresToolkit._get_foreign_keys_query` (NEW) | `_introspect_table_full` | introspection query | new |
| `SCHEMA_TOOL_USAGE_LAYER` | `_build_database_prompt_builder()` | `builder.add(...)` | prompts.py:78-85 |

### Does NOT Exist (Anti-Hallucination)

- ~~`CachePartition.get(...)` with `required=` kwarg~~ — current API is
  `get_table_metadata(schema, table)` with no completeness arg. Introduced
  here.
- ~~`CachePartition.list(...)`~~ — does not exist; introduced here.
- ~~`CachePartition.search(...)` with `completeness_min=`~~ — current
  closest is `search_similar_tables(schema_names, query, limit)`.
  Introduced here.
- ~~`CachePartitionConfig.ttl_by_completeness`~~ — does not exist;
  introduced here. Current `CachePartitionConfig` only has `namespace`,
  `lru_maxsize`, `lru_ttl`, `redis_ttl` (cache.py:30).
- ~~`SQLToolkit.describe_table(...)`~~ — does not exist; introduced here.
- ~~`SQLToolkit.list_tables(...)`~~ — **NOT introduced**. Excluded by Q1
  decision (no extra tools beyond `describe_table`).
- ~~`SQLToolkit.search_tables(...)`~~ — **NOT introduced**. `search_schema`
  is renamed in-place by Q1 decision — its name stays, behaviour is fixed.
- ~~`SQLToolkit._inflight`~~ — does not exist; introduced here for
  concurrency coalescing.
- ~~`PostgresToolkit._get_foreign_keys_query`~~ — does not exist today.
  Introduced here.
- ~~`PostgresToolkit._get_indexes_query`~~ — does not exist today.
  Introduced here.
- ~~`TableMetadata.completeness`~~ — does not exist; introduced here.
- ~~`TableMetadata.satisfies(...)`~~ — does not exist; introduced here.
- ~~`Completeness` enum~~ — does not exist anywhere in parrot today.
- ~~`MetadataSource` Literal~~ — does not exist today.
- The `DatabaseAgent` subclass in navigator-plugins (`SQLAnalyst`) sets
  `model = "gemini-3-flash-preview"` as a class attribute, but
  `DatabaseAgent.ask()` delegates to `self._llm.ask(...)` which reads
  model from a separate LLM-client configuration. This spec does NOT
  fix that model-override issue — it is a separate defect to be
  addressed in a follow-up spec.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `Completeness` as an `IntEnum` so `meta.completeness >= required`
  is the canonical check; do not introduce a `Set[Capability]` style.
  Numeric ordering matches "strictly subsumes" semantics.
- For backwards-compat, `Completeness.FULL` is the default value of the
  new field on `TableMetadata`. Existing call sites that construct
  `TableMetadata` via `_build_table_metadata` (sql.py:811) will get
  `FULL` automatically — and they ARE full introspections, so this is
  correct.
- For the frontend pre-warm path (navigator-plugins `_consume_schema_block`),
  the parser MUST set `completeness` explicitly per the tag in the wire
  format. Default-to-FULL is wrong for stubs.
- `_score_against_cache` rework: accumulate `(score, meta)` tuples,
  `sorted(scored, key=lambda x: x[0], reverse=True)`, then truncate.
  Verified by `test_cache_search_sorts_by_score`.
- Concurrency: use `asyncio.Lock` per `_inflight` map mutation; the
  futures themselves are awaited outside the lock. Pattern: check map
  under lock → if hit, await outside lock → if miss, create future under
  lock, release lock, do work, set result on future, remove from map
  under lock.
- TTL: extend `CachePartitionConfig` with `ttl_by_completeness:
  Dict[Completeness, int]` (defaults `{NAME_ONLY: 86400, WITH_COLUMNS:
  21600, FULL: 3600}`). The effective TTL for a tier is
  `min(tier_ttl, ttl_by_completeness[entry.completeness])`. Tunable per
  agent via `DatabaseAgent(cache_ttl_by_completeness=...)` forwarded
  into `CachePartitionConfig`.
- `pg_catalog` queries: schema-qualify every table reference
  (`pg_catalog.pg_class`, not bare `pg_class`) to avoid `search_path`
  surprises. Use parameter binding for schema/table names — do not
  interpolate even when the values come from `allowed_schemas`.
- For vector-path completeness filtering (Q5): vector store entries are
  stored at whatever completeness the most-recent
  `_store_in_vector_store` saw. Reading: fetch candidates, then
  per-candidate `await self.get(schema, table, required=completeness_min,
  max_age=max_age)` — if `None`, drop. This double-checks via the
  structural cache and handles eviction.

### Known Risks / Gotchas

- **Backwards compatibility of `TableMetadata` constructors.** Old call
  sites do `TableMetadata(schema=..., tablename=..., table_type=...,
  full_name=...)`. The new fields must be keyword-only with defaults, or
  this breaks every caller. Use `field(default=...)` for all three.
- **Default `FULL` is correct for DB-built metadata, wrong for stubs.**
  Anywhere a `TableMetadata` is constructed without going through
  `_build_table_metadata` or `_introspect_table_full`, the constructor
  must explicitly set `completeness`. Reviewers should grep for
  `TableMetadata(` outside the toolkit during code review.
- **Redis-stored old entries don't have `completeness`/`loaded_at`/`source`.**
  During the upgrade, Redis may hold pre-FEAT-177 `TableMetadata` dicts
  without the new fields. Deserialization must default to `FULL`/
  `datetime.utcnow()`/`"unknown"` so existing cached entries are not
  treated as stubs. After max Redis TTL expiry, all entries are re-stored
  with the new fields.
- **`pg_catalog` migration semantics.** `pg_catalog` queries can surface
  things `information_schema` filters out (e.g., system columns like
  `xmin`, partitions, inherited tables). The new `_get_columns_query`
  must filter `attnum > 0 AND NOT attisdropped` to match the old
  visible-column set. Add `test_pg_catalog_full_introspection_matches_information_schema`
  to catch regressions.
- **Coordinated release with navigator-plugins.** The frontend wire-format
  change (Q3 explicit tags) requires:
  1. ai-parrot FEAT-177 ships first (no wire format dependency)
  2. navigator-plugins parser update (Module 8) ships — accepts both
     legacy and tagged formats
  3. Frontend emitter (Module 9) starts sending tagged form
  Order matters: if frontend ships tags before parser accepts them, the
  pre-warm silently fails to populate completeness correctly.
- **Vector store path bypasses some completeness invariants.** Vector
  candidates are filtered post-hoc, but if the vector store holds stale
  embeddings for a renamed/dropped table the filter can return a
  metadata-mismatch. Mitigation: the post-hoc `get(...)` call against
  the structural cache will return `None` for entries that no longer
  exist, naturally dropping them.
- **Concurrent describe of the same table.** Existing semaphore in
  `_search_in_database` (sql.py:790) handles 4-way concurrency for batch
  metadata builds. The new `_inflight` coalescing must compose with that
  semaphore, not replace it. Concretely: `_introspect_table_full`
  acquires `_inflight_lock` to claim the future, then enters the
  semaphore-bounded `_build_table_metadata` path.
- **navigator-plugins dual-format parser.** Module 8's parser must handle
  both `table(col:type;...)` (legacy) and `table[WITH_COLUMNS](col:type;...)`
  (new) for at least one release. Add a test asserting both formats parse.
- **Repurposed `db_generate_query` is a behaviour-breaking change for
  consumers.** Old behaviour: returned a YAML context plus a prompt
  template. New behaviour: returns a SELECT skeleton with real columns,
  embedded in the YAML. The output shape is similar but not identical.
  Consumers that string-matched the old output may break. Document the
  change in CHANGELOG.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| *(none new)* | — | All work uses existing deps (asyncio, dataclasses, pydantic, yaml) |

---

## 8. Open Questions

> All seven questions from the initial draft are now resolved. They are
> kept here with their resolutions as the audit trail.

- [x] **Q1 — Tool naming during deprecation** — *Resolved 2026-05-15*:
      **Rename in-place.** `db_search_schema` keeps its name and signature;
      its behaviour is fixed. No `db_search_tables` is introduced. Only
      `db_describe_table` is added as a new tool (necessary for the Q4
      decision). No `db_list_tables` is added.
- [x] **Q2 — TTL defaults & tunability** — *Resolved 2026-05-15*:
      **24h / 6h / 1h with tunability.** Defaults are `NAME_ONLY=86400s`,
      `WITH_COLUMNS=21600s`, `FULL=3600s`. Tunable via
      `CachePartitionConfig.ttl_by_completeness`, forwarded from
      `DatabaseAgent(cache_ttl_by_completeness=...)`.
- [x] **Q3 — Frontend wire format** — *Resolved 2026-05-15*:
      **Explicit tags.** Pre-warm format becomes
      `table[NAME_ONLY]` / `table[WITH_COLUMNS](col:type;...)`. Requires
      coordinated change: parser update (Module 8) ships before frontend
      emitter (Module 9). Parser keeps legacy fallback for one release.
- [x] **Q4 — `db_generate_query` fate** — *Resolved 2026-05-15*:
      **Repurpose as skeleton builder.** Keeps name and signature.
      Internally calls `db_describe_table` for each target (forcing real
      column data) and returns a templated `SELECT` skeleton plus
      per-table YAML metadata. If `target_tables` is empty, uses
      `db_search_schema` to discover candidates first.
- [x] **Q5 — Vector store path with completeness** — *Resolved 2026-05-15*:
      **Filter post-hoc.** Vector candidates are returned by the embedding
      search, then each is re-validated against the structural cache via
      `get(required=completeness_min, max_age=max_age)`. Candidates that
      no longer satisfy the contract are dropped before merge.
- [x] **Q6 — Per-user cache partitioning** — *Resolved 2026-05-15*:
      **Out of scope.** Cache namespace remains keyed by toolkit
      (`postgresql_public`). Risk: if introspections leak across users
      with different schema permissions, metadata exposure is possible.
      Accepted because, in navigator's current single-DSN model, all
      users share the same effective permissions. Per-user partitioning
      is a follow-up.
- [x] **Q7 — `pg_catalog` vs `information_schema`** — *Resolved 2026-05-15*:
      **Migrate in this spec.** All `PostgresToolkit._get_*` queries are
      rewritten against `pg_catalog` (Module 5). Two new query hooks are
      added: `_get_indexes_query` and `_get_foreign_keys_query`. Future
      DDL-detection work (via `pg_class.relfilenode`) becomes possible
      after this lands.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`. Modules 1–6 are sequential and
  edit overlapping files (`models.py`, `cache.py`, `toolkits/sql.py`,
  `toolkits/postgres.py`, `prompts.py`). Parallelisation would cause
  merge conflicts.
- **Parallelisable subset**: Module 7 (tests) can be partially developed
  in parallel against Module 1–4's interfaces once those are committed.
  Module 5 (pg_catalog migration) and Module 6 (prompt layer) are
  independent of each other and could be parallelised after Modules
  1–4 land.
- **Downstream modules** (8 and 9) are separate worktrees on a different
  repo (`navigator-plugins`). They are blocked by FEAT-177 landing in
  ai-parrot but do not block FEAT-177 from merging.
- **Cross-feature dependencies**: none in ai-parrot. Downstream
  coordination required with the frontend team for Module 9.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-15 | jfrruffato | Initial draft after debugging `sql_analyst` failures on `pokemon.stores` and `networkninja.forms` JOINs |
| 0.2 | 2026-05-15 | jfrruffato | Resolved all 7 open questions; reworked tool surface (in-place rename, repurposed `generate_query`, new `describe_table`); added `pg_catalog` migration module; added frontend wire format change as a downstream module |
