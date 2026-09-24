---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [wiki, schema-plane, database-agent, sqlglot, mcp, dev-loop]
---

# Feature Specification: SQL Schema Plane

**Feature ID**: FEAT-600
**Date**: 2026-09-24
**Author**: Jesus Lara (drafted with Claude)
**Status**: draft
**Target version**: next minor of `ai-parrot`
**Exploration**: `sdd/proposals/schema-plane.brainstorm.md` (Option B, all 9 questions resolved) ·
`sdd/proposals/sql-schema-plane.proposal.md` (FEAT-600 research, 25 findings under `sdd/state/FEAT-600/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

Every agent that touches a relational source re-discovers the data model at run time.
`SQLToolkit.describe_table` / `search_schema` go to `information_schema` (or `pg_catalog` /
BigQuery `INFORMATION_SCHEMA`) whenever the `CachePartition` misses, and the partition is a
**TTL cache** (LRU 30 min, Redis 1 h, capped further by `ttl_by_completeness`): per process or
per Redis, private to `DatabaseAgent`, and empty on every cold start. Concretely:

1. **No durable, shared knowledge of the data model.** The same `TableMetadata` is introspected
   over and over — per agent instance, per deploy, per environment. On BigQuery `INFORMATION_SCHEMA`
   reads are billed and rate-limited.
2. **Coding agents have no data model at all.** An `sdd-coder` writing a repository or a
   `DatabaseToolkit` subclass has no database connection in the worktree and no page to read;
   `wikitoolkit mcp` exposes `file:` / `sym:` / `issue:` / decision pages, nothing about tables.
   `SQLQuerySource.prefetch_schema()` returns `{}`.
3. **Relations are not a graph.** `TableMetadata.foreign_keys` is a list inside one entry; "what
   joins to `epson.sales`?" cannot be asked. Join-path discovery is the single most useful thing
   for text-to-SQL.
4. **No place for meaning.** `information_schema` will never say "`store_id` here is the T-ROC store
   id" or "`sales_v1` is deprecated". `wiki_remember` exists but has no table page to point at.

### Goals

- G1 — A durable **schema plane** (`.parrot/schema/schema.db`) holding `source:` / `schema:` /
  `table:` pages with DDL, columns, relations and freshness metadata, mounted as a read-only
  wikitoolkit overlay namespace so `wiki_query` / `wiki_related` / `wiki_page` see tables.
- G2 — Ids are **kind-first, origin-second**: `table:<origin>/<schema>.<table>`; the owner's
  *origin:object* form (`bigquery:epson.sales`) is accepted on input by `normalize_ref()`.
- G3 — **Two producers, one record**: live introspection through the existing `SQLToolkit`
  dialect hooks and offline DDL ingest through `sqlglot`, both emitting
  `parrot.bots.database.models.TableMetadata`.
- G4 — **Read path never introspects**: lookups return the stored page with `age` / `stale`;
  re-introspection happens only for hit tables, on `sync --changed` or on a proven-stale
  database error.
- G5 — **Runtime integration**: `CachePartition` gains an optional plane tier after Redis with
  write-through; `DatabaseAgent` warms from the plane; behaviour is byte-identical when no
  plane is configured.
- G6 — **Annotations survive sync**: `wiki_remember(..., link_page_id="table:…")` notes are
  linked, never rewritten, by `schema sync`.
- G7 — **Security**: no credential ever enters a page; `source:` pages carry a `dsn_env` *name*;
  `sample_data` is off by default.
- G8 — **Rootless-ready**: `SchemaPlaneService.from_root()` for the shared-root git policy and
  `from_dir()` for a `DatabaseAgent` without a repo (aligned with FEAT-569).

### Non-Goals (explicitly out of scope)

- Columns as `col:` pages — v1 uses a `columns` side table; pages can be added later without
  changing table ids (resolved in brainstorm).
- Edge attributes (`attrs` column on `edges`) — v1 keeps FK edges plain `references` and stores the
  column pair in the `columns` table (resolved in brainstorm).
- `maps_to` (Python model → table) extraction — v2.
- Schema history / bitemporal archive — Option D territory; `schema diff` is the change report.
- Plane-aware `SQLQuerySource.prefetch_schema` and `dq_get_table_metadata` — follow-ups.
- Retiring the legacy `parrot_tools.database.models.TableMetadata` — avoided, not removed.
- Write tools over MCP — sync needs credentials the MCP does not hold; writes are CLI-only.
- A Postgres/ArangoDB-backed fleet plane and widening `WikiProjectConfig.backend` — follow-up
  after FEAT-569 lands (resolved in brainstorm).
- Storing tables in the main `wiki.db` (brainstorm Option A) and a durable `CachePartition`
  without the wiki (Option C) were rejected — see `sdd/proposals/schema-plane.brainstorm.md`.

---

## 2. Architectural Design

### Overview

Mirror the FEAT-566 ledger plane: a `SchemaStore(SQLiteWikiStore)` in its own directory
(`<shared>/.parrot/schema/schema.db`), opened by `SchemaPlaneService.from_root(root)` (or
`from_dir(dir)`) and mounted in `mcp_server.py` as a read-only
`NamespaceHandle(name="schema", overlay_prefixes=["source", "schema", "table"])` next to the ledger
handle. `FederatedWikiStore._route_bare_overlay_id` already routes a bare id by its kind prefix to
the overlay that declares it and `neighbors()` hydrates cross-kind edges (`table:` ↔ `file:` ↔
`sym:`) for every overlay, so the plane inherits the whole read path.

**Id grammar** (decided): `source:<origin>` · `schema:<origin>/<schema>` ·
`table:<origin>/<schema>.<table>`. `<origin>` is a declared source alias that **defaults to the
dialect** (keys of `_SQLGLOT_DIALECT_MAP`); a second source of the same dialect must name itself.
`normalize_ref("bigquery:epson.sales") → "table:bigquery/epson.sales"` is applied by every lookup
tool and CLI verb.

**Page shape**: `body` = frontmatter (origin, dialect, schema, table, table_type, completeness,
source, introspected_at, content_hash, row_count) + `## DDL` (canonical `CREATE TABLE` rendered via
`sqlglot.exp.Create(...).sql(dialect=…)`) + `## Columns` + `## Relations`. `content_hash` = sha1 of
the normalised `TableMetadata` JSON minus volatile fields (`row_count`, `last_accessed`,
`access_frequency`, `avg_query_time`, `loaded_at`). Columns live in a `columns` side table
(mirrors `symbols`) with a per-column `fk_target` — this is where the FK column pair lives; the
edge itself is a plain `references` with `provenance="extracted"`.

**Edges**: `contains` (`source`→`schema`→`table`), `references` (FK), `depends_on` (view → table),
`defined_in` (`table` → `file:<migration>.sql`).

**Producers**: (1) `schema sync <origin>` instantiates the matching `SQLToolkit` subclass from the
`source:` config + `dsn_env`, calls `describe_table` (FULL) per table, writes pages via
`replace_source_slice(source_id="schema:<origin>")`; `--changed` rewrites only drifted
`content_hash`es. (2) `schema ingest-ddl <paths> --origin <o> --dialect <d>` splits `.sql` files
into statements, parses each with `sqlglot.parse_one(read=dialect)` inside its own `try`, folds
`exp.Create` / `exp.ColumnDef` (incl. column-level `PrimaryKeyColumnConstraint`) /
`exp.PrimaryKey` / `exp.ForeignKey` / `exp.Alter` in file order, and adds `defined_in` edges.
**Merge rule** (decided): live is authoritative for facts; DDL only creates pages for tables with
no live counterpart (`source="ddl"`) and always contributes `defined_in`; divergence is reported
by `schema diff`, never resolved by timestamp.

**Freshness**: the read path never introspects. `wiki_schema_lookup` returns `age` and `stale`
(from `SchemaPlaneConfig.stale_after_days` per completeness). Repair triggers: `schema sync
--changed` (cron / post-merge) and **error-driven read-repair** — when `SQLToolkit.execute_query`
classifies an error as `column does not exist` / `relation does not exist`, it re-runs
`describe_table` for the referenced tables and write-through upserts the plane (shape of
`StructuralService._ensure_fresh`: non-blocking lock, `stale=True` when busy).

**Runtime**: `CachePartition(plane=…, origin=…)` inserts a plane tier between Redis and the vector
store; `store_table_metadata` writes through when `plane_write=True`; `_warm_table_cache` prefers
the plane. `DatabaseToolkitConfig.origin` (default `database_type`) is the alias key;
`tk_id` is untouched.

**Tools**: MCP `wiki_schema_lookup`, `wiki_schema_search`, `wiki_schema_neighbors`,
`wiki_schema_sources` (one action per tool); `SchemaPlaneToolkit(AbstractToolkit)` wrapping the
same four for any agent; CLI `wikitoolkit schema {sources, add-source, sync, ingest-ddl, diff,
lookup}`; write verbs refuse to run inside a linked worktree.

### Component Diagram
```
                 wikitoolkit schema …  (CLI, M4)          Claude Code / agents
                        │                                        │
     producers/live.py ─┤  producers/ddl.py                      │ MCP wiki_schema_* (M5)
   (SQLToolkit hooks)   │  (sqlglot fold)                        │ SchemaPlaneToolkit (M5)
                        ▼                                        ▼
               SchemaPlaneService (M2/M3) ──► SchemaStore(SQLiteWikiStore) + columns  (M1)
                        ▲                          │   .parrot/schema/schema.db
   CachePartition tier ─┘ (M6)                     ▼
   DatabaseAgent / SQLToolkit read-repair    NamespaceHandle("schema") ──► FederatedWikiStore
                                                   (mcp_server.py, M5)      wiki_query/related/page
                                                                              DevLoopWikiSearch (M7)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `knowledge/wiki/mcp_server.py::create_wiki_mcp_server` | extends | second overlay handle + `create_schema_tools` (F001) |
| `knowledge/wiki/federation.py::FederatedWikiStore` | uses | bare-id routing + cross-kind neighbors unchanged (F002) |
| `knowledge/wiki/store.py::SQLiteWikiStore` | extends | `SchemaStore` subclass, `columns` side table (F003) |
| `knowledge/wiki/project.py::WikiProjectConfig` | extends | `schema: SchemaPlaneConfig`, `schema_path()` (F004) |
| `knowledge/wiki/ledger/{store,service}.py` | pattern | template for store/service (F005) |
| `knowledge/wiki/cli.py` | extends | `schema` group (F021) |
| `knowledge/wiki/claude_code/assets.py` | modifies | ingest-ddl line in `git_hook_block`; four `mcp__wikitoolkit__wiki_schema_*` permissions (F012) |
| `knowledge/wiki/tools.py::WikiRememberTool` | uses | annotations as-is (F015) |
| `bots/database/models.py` | extends | `MetadataSource += "ddl"` (F006) |
| `bots/database/cache.py::CachePartition` | modifies | plane tier + write-through, no-op when unset (F007) |
| `bots/database/toolkits/base.py::DatabaseToolkitConfig` | extends | `origin` field (F009) |
| `bots/database/toolkits/sql.py::SQLToolkit` | modifies | read-repair hook, `validate_query` wording, `_warm_table_cache` from plane, `generate_query` join-path context (F008, F010) |
| `bots/database/agent.py::DatabaseAgent` | extends | `schema_plane` argument, origin propagation (F009) |
| `flows/dev_loop/wiki_search.py::DevLoopWikiSearch` | extends | `table:` hits in research context (F020) |
| `tools/dataset_manager/sources/sql.py` | none (follow-up) | `prefetch_schema` stays `{}` in v1 (F011) |

### Data Models
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py  (new)
from pydantic import BaseModel, Field
from parrot.bots.database.models import TableMetadata, Completeness   # verified: bots/database/models.py:97,131

class SchemaSourceConfig(BaseModel):
    """One declared SQL source; never holds a DSN, only the env-var *name*."""
    alias: str                                  # origin; defaults to dialect at add-source time
    dialect: str                                # key of _SQLGLOT_DIALECT_MAP (sql.py:45)
    dsn_env: str                                # navconfig / env variable NAME
    allowed_schemas: list[str] = Field(default_factory=lambda: ["public"])
    tables: list[str] | None = None             # optional "schema.table" allowlist
    include_samples: list[str] = Field(default_factory=list)   # per-table sample_data allowlist

class SchemaPlaneConfig(BaseModel):
    """`schema:` block of .parrot/wiki.json (mirrors DecisionConfig on WikiProjectConfig)."""
    enabled: bool = True
    sources: dict[str, SchemaSourceConfig] = Field(default_factory=dict)
    stale_after_days: dict[int, int] = Field(default_factory=lambda: {1: 30, 2: 14, 3: 7})  # keyed by int(Completeness)

class ColumnRecord(BaseModel):
    """Row of the `columns` side table."""
    table_id: str                               # table:<origin>/<schema>.<table>
    ordinal: int
    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    comment: str | None = None
    is_primary_key: bool = False
    fk_target: str | None = None                # "table:<origin>/<schema>.<table>.<column>"

class TableRecord(BaseModel):
    """TableMetadata plus the plane-only identity fields."""
    origin: str
    dialect: str
    metadata: TableMetadata                     # the canonical bots/database record
    content_hash: str
    introspected_at: str                        # ISO-8601 UTC
    defined_in: list[str] = Field(default_factory=list)   # file:<rel_path> ids
    model_config = {"arbitrary_types_allowed": True}       # TableMetadata is a dataclass

class LookupResult(BaseModel):
    """Payload of wiki_schema_lookup / `schema lookup`."""
    page_id: str
    frontmatter: dict
    ddl: str
    columns: list[ColumnRecord]
    relations: list[dict]                       # {rel, target, provenance, column_pair?}
    annotations: list[dict]                     # mem-* pages via neighbors(rel="about")
    age_days: float
    stale: bool

class SyncReport(BaseModel):
    created: list[str]; updated: list[str]; unchanged: list[str]; removed: list[str]
    failed: dict[str, str] = Field(default_factory=dict)       # table_id -> error
    parse_errors: dict[str, str] = Field(default_factory=dict) # file -> error (ingest-ddl)
```

### New Public Interfaces
```python
from parrot.knowledge.wiki.schema import (
    SchemaStore, SchemaPlaneService, SchemaPlaneToolkit, create_schema_tools,
    table_concept_id, parse_table_id, normalize_ref,
)
# CLI:  wikitoolkit schema sources | add-source | sync | ingest-ddl | diff | lookup
# MCP:  wiki_schema_lookup · wiki_schema_search · wiki_schema_neighbors · wiki_schema_sources
# Runtime: CachePartition(..., plane=SchemaPlaneReader | None, plane_write=False, origin=None)
#          DatabaseAgent(..., schema_plane: SchemaPlaneService | Path | None = None)
#          DatabaseToolkitConfig.origin: str | None  (default → database_type)
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Plane foundation | yes | id grammar fixed; `SchemaStore(SQLiteWikiStore)` + `columns` DDL below; `content_hash` field list fixed; `SchemaPlaneConfig` mirrors `DecisionConfig`; `MetadataSource` literal extended | — |
| M2: Live producer + service core | yes | uses `SQLToolkit.describe_table` per table, `replace_source_slice(source_id="schema:<origin>")`; `from_root`/`from_dir` mirror `LedgerService.from_root`; `SyncReport` shape fixed | — |
| M3: DDL producer + diff | yes | per-statement `sqlglot.parse_one` with isolation; fold rules and merge rule fixed below | — |
| M4: CLI group + hook | yes | `@wiki.group(name="schema")` after ledger; write verbs guard with `is_linked_worktree`; hook line inside existing `if [ ! -f .git ]` | — |
| M5: Tools + MCP mount | yes | four `AbstractTool`s mirroring `structural/tools.py`; `SchemaPlaneToolkit(AbstractToolkit)`; mount block copies ledger block | — |
| M6: Database runtime tier | yes | tier position (after Redis, before vector), write-through flag, `origin` field default, repair hook at `sql.py:349`; plane-off parity gate | — |
| M7: Dev-loop research context | yes | mirror `_get_ledger_context` best-effort fold | — |
| M8: Docs | yes | `docs/wiki/schema-plane.md` + CLAUDE.md wiki section paragraph | — |

### Module 1: Plane Foundation (models, ids, render, store, config)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/schema/{__init__,models,ids,render,store}.py` (new); modifies `knowledge/wiki/project.py`, `bots/database/models.py`
- **Responsibility**: the contract every other module imports — records, id grammar, page renderer, `SchemaStore` with `columns` side table, `SchemaPlaneConfig` + `schema_path`.
- **Depends on**: `SQLiteWikiStore`, `WikiPageRecord`, `TableMetadata`, `sqlglot`.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/schema/ids.py  (new)
  KINDS = ("source", "schema", "table")
  def source_concept_id(origin: str) -> str: """`source:<origin>`."""
  def schema_concept_id(origin: str, schema: str) -> str: """`schema:<origin>/<schema>`."""
  def table_concept_id(origin: str, schema: str, table: str) -> str:
      """`table:<origin>/<schema>.<table>`; lower-cases nothing — dialect case is preserved."""
  def parse_table_id(concept_id: str) -> tuple[str, str, str]:
      """Return (origin, schema, table); raises ValueError for any other kind."""
  def normalize_ref(ref: str, *, sources: dict[str, "SchemaSourceConfig"] | None = None) -> str | list[str]:
      """Accept `table:o/s.t`, bare `o:s.t`, or `s.t`; return the table id, or the candidate
      ids when `s.t` is ambiguous across sources (never guesses)."""

  # knowledge/wiki/schema/render.py  (new)
  VOLATILE_FIELDS = ("row_count", "last_accessed", "access_frequency", "avg_query_time", "loaded_at")
  def content_hash(metadata: TableMetadata) -> str:
      """sha1 of the sorted-key JSON of `dataclasses.asdict(metadata)` minus VOLATILE_FIELDS."""
  def render_ddl(record: TableRecord) -> str:
      """Canonical CREATE TABLE via sqlglot.exp.Create(...).sql(dialect=_SQLGLOT_DIALECT_MAP[record.dialect])."""
  def render_page(record: TableRecord) -> tuple[WikiPageRecord, list[ColumnRecord], list[tuple[str, str, str, str]]]:
      """Return (page, columns, edges). page.category="table", page.origin="ingest",
      page.source_id=f"schema:{record.origin}", page.content_hash=record.content_hash;
      edges are (src, dst, rel, provenance) with rel in {contains, references, depends_on, defined_in}."""
  def render_source_page(cfg: SchemaSourceConfig) -> WikiPageRecord: """`source:` page — alias, dialect, schemas, dsn_env NAME only."""
  def render_schema_page(origin: str, schema: str, table_ids: list[str]) -> WikiPageRecord: ...

  # knowledge/wiki/schema/store.py  (new)
  class SchemaStore(SQLiteWikiStore):  # SQLiteWikiStore verified: knowledge/wiki/store.py:855, __init__ :903
      """SQLiteWikiStore specialisation for schema.db: adds the `columns` side table."""
      COLUMNS_DDL = """CREATE TABLE IF NOT EXISTS columns (
          table_id TEXT NOT NULL, ordinal INTEGER NOT NULL, name TEXT NOT NULL, data_type TEXT NOT NULL,
          nullable INTEGER NOT NULL DEFAULT 1, dflt TEXT, comment TEXT, is_primary_key INTEGER NOT NULL DEFAULT 0,
          fk_target TEXT, PRIMARY KEY (table_id, name));
      CREATE INDEX IF NOT EXISTS idx_columns_name ON columns(name);
      CREATE INDEX IF NOT EXISTS idx_columns_fk ON columns(fk_target);"""
      async def upsert_columns(self, columns: list[ColumnRecord]) -> int:
          """Replace all rows of each table_id present in `columns` (delete-then-insert inside one _write())."""
      async def columns_for(self, table_id: str) -> list[ColumnRecord]: ...
      async def find_columns(self, name: str | None = None, fk_target_prefix: str | None = None, limit: int = 50) -> list[ColumnRecord]: ...
      async def replace_schema_slice(self, origin: str, pages: list[WikiPageRecord], columns: list[ColumnRecord],
                                     edges: list[tuple[str, str, str, str]]) -> dict[str, Any]:
          """replace_source_slice(f"schema:{origin}", pages, edges) + columns replace for the removed/added table ids,
          in one transaction. verified: store.py:1614 (replace_source_slice)."""

  # knowledge/wiki/project.py  (modifies :478 and :520)
  class WikiProjectConfig(BaseModel):
      schema: "SchemaPlaneConfig" = Field(default_factory=SchemaPlaneConfig)   # after `decisions:` — verified: project.py:478
      def schema_path(self, root: Path) -> Path:
          """`<root>/.parrot/schema` — mirrors ledger_path (verified: project.py:520)."""

  # bots/database/models.py  (modifies :108)
  MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "ddl", "unknown"]
  ```

### Module 2: Live Producer + Service Core
- **Path**: `knowledge/wiki/schema/{service,producers/__init__,producers/live}.py` (new)
- **Responsibility**: `SchemaPlaneService` (open the plane, sync from a live source, lookup/neighbors/search read API); live producer over `SQLToolkit` subclasses.
- **Depends on**: M1; `SQLToolkit`, `PostgresToolkit`, `BigQueryToolkit`, `DatabaseToolkitConfig`; `find_shared_root`, `load_effective_config`, `sqlite_policy_from_config`.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/schema/producers/live.py  (new)
  def toolkit_for(cfg: SchemaSourceConfig, dsn: str) -> SQLToolkit:
      """PostgresToolkit for postgres/postgresql, BigQueryToolkit for bigquery, else SQLToolkit
      (verified: toolkits/postgres.py:28, toolkits/bigquery.py:19, toolkits/sql.py:62)."""
  async def introspect(cfg: SchemaSourceConfig, dsn: str, *, tables: list[str] | None = None) -> tuple[list[TableRecord], dict[str, str]]:
      """describe_table (FULL) per allowed table; returns (records, failed) — partial failure never raises.
      verified: SQLToolkit.describe_table sql.py:183, search_schema sql.py:113."""

  # knowledge/wiki/schema/service.py  (new)
  class SchemaPlaneReader(Protocol):
      """Read surface consumed by CachePartition (M6) — keeps bots/database free of wiki imports."""
      async def get_table(self, origin: str, schema: str, table: str) -> TableMetadata | None: ...
      async def put_table(self, origin: str, dialect: str, metadata: TableMetadata) -> None: ...
      async def list_tables(self, origin: str, schema: str | None = None) -> list[str]: ...

  class SchemaPlaneService:
      """Application-facing service over SchemaStore (mirrors LedgerService, verified: ledger/service.py:116)."""
      def __init__(self, store: SchemaStore, config: SchemaPlaneConfig, plane_dir: Path, shared_root: Path | None) -> None: ...
      @classmethod
      def from_root(cls, root: Path | None = None) -> "SchemaPlaneService":
          """find_shared_root(root) → load_effective_config → config.schema_path → SchemaStore(dir/'schema.db', wiki_name='schema')."""
      @classmethod
      def from_dir(cls, plane_dir: Path, *, config: SchemaPlaneConfig | None = None, read_only: bool = True) -> "SchemaPlaneService":
          """Rootless constructor for a DatabaseAgent without a git checkout (aligned with FEAT-569 TASK-3354)."""
      @property
      def store(self) -> SchemaStore: ...
      async def sync(self, origin: str, *, tables: list[str] | None = None, changed_only: bool = False,
                     dsn_resolver: Callable[[str], str] | None = None) -> SyncReport:
          """Introspect and replace the `schema:<origin>` slice; `changed_only` compares content_hash via page_hashes()
          (verified: store.py:837) and rewrites only drifted tables. Removed tables are dropped from the slice
          (annotations become dangling `about` edges, never deleted)."""
      async def lookup(self, ref: str) -> LookupResult | list[str]:
          """normalize_ref → get_page + columns_for + neighbors(); age from introspected_at, stale from stale_after_days."""
      async def neighbors(self, ref: str, *, depth: int = 1, rel: str | None = "references") -> list[dict]:
          """FK graph walk to `depth`; each hop carries the column pair from `columns.fk_target`."""
      async def search(self, query: str, *, limit: int = 20) -> list[dict]:
          """search_fts over table pages (verified: store.py:2004) merged with find_columns(name=...) hits."""
      async def sources(self) -> list[SchemaSourceConfig]: ...
      # SchemaPlaneReader implementation (get_table / put_table / list_tables) delegating to the above.
  ```

### Module 3: DDL Producer + Diff
- **Path**: `knowledge/wiki/schema/producers/ddl.py` (new); extends `service.py` (`ingest_ddl`, `diff`)
- **Responsibility**: fold `.sql` files into `TableRecord`s without a database; live-vs-DDL diff.
- **Depends on**: M1, M2; `sqlglot` (30.x installed, `>=20.0` declared).
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/schema/producers/ddl.py  (new)
  def split_statements(sql_text: str) -> list[str]:
      """Statement-level split (sqlglot tokenizer, `;` outside strings/`$$` bodies) so one ParseError never loses a file (F025)."""
  def fold_ddl(files: list[Path], *, origin: str, dialect: str, root: Path) -> tuple[list[TableRecord], dict[str, str]]:
      """Parse each statement with sqlglot.parse_one(stmt, read=dialect) in its own try; fold exp.Create(kind=TABLE) →
      TableMetadata(source="ddl", completeness=FULL), exp.ColumnDef (+ PrimaryKeyColumnConstraint / NotNullColumnConstraint /
      DefaultColumnConstraint / References), exp.PrimaryKey, exp.ForeignKey, exp.Alter (ADD/DROP/ALTER COLUMN, ADD CONSTRAINT)
      in file-name order; exp.Create(kind=VIEW) → table_type="VIEW" + depends_on targets; `Command` fallbacks and
      unsupported statements are skipped. Returns (records, parse_errors) — never raises for a bad file.
      Each record.defined_in gets file_concept_id(rel_path) (verified: symbols.py file_concept_id)."""

  # knowledge/wiki/schema/service.py  (extends M2)
  class SchemaPlaneService:
      async def ingest_ddl(self, paths: list[Path], *, origin: str, dialect: str, changed_only: bool = False) -> SyncReport:
          """Merge rule (decided): a DDL record replaces a page only if no live page exists for that table id
          (page.summary/frontmatter source != live); otherwise only `defined_in` edges are added. parse_errors reported."""
      async def diff(self, origin: str, *, live: list[TableRecord] | None = None) -> list[dict]:
          """Per-table column/type/constraint differences between live and DDL records for one origin; optional
          `--ledger` filing is done by the CLI (M4), not here."""
  ```

### Module 4: CLI Group + Git Hook Line
- **Path**: modifies `knowledge/wiki/cli.py` (after `ledger` group, :2764), `knowledge/wiki/claude_code/assets.py` (:187, :62)
- **Responsibility**: `wikitoolkit schema` verbs; post-merge DDL ingest inside the existing worktree guard; MCP permission entries.
- **Depends on**: M2, M3.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/cli.py  (modifies: new group after cli.py:2764 `@wiki.group(name="ledger")`)
  @wiki.group(name="schema")
  def schema() -> None:
      """Manage the SQL schema plane (sources, sync, DDL ingest, diff, lookup)."""
  @schema.command("sources")            # list declared sources (alias, dialect, schemas, dsn_env name)
  @schema.command("add-source")         # ALIAS --dialect --dsn-env --schemas [--tables]; refuses alias collision
  @schema.command("sync")               # ORIGIN [--tables a.b,c.d] [--changed] [--json]; refuses linked worktree
  @schema.command("ingest-ddl")         # PATHS... --origin --dialect [--changed] [--json]; refuses linked worktree
  @schema.command("diff")               # ORIGIN [--ledger] → optional `ledger open --kind tech_debt --about table:…`
  @schema.command("lookup")             # REF (bare origin:object accepted) [--json]
  def _refuse_in_linked_worktree(root: Path) -> None:
      """raise click.UsageError when is_linked_worktree(root / '.git') (verified: project.py:1185)."""

  # knowledge/wiki/claude_code/assets.py  (modifies :187 — inside the existing `if [ ! -f .git ]` block)
  #   f"    {wt_bin} upsert --changed --quiet >/dev/null 2>&1 || true\n"
  #   f"    {wt_bin} schema ingest-ddl --changed --quiet >/dev/null 2>&1 || true\n"   # NEW line, same guard
  # (modifies :62 — permission list) + "mcp__wikitoolkit__wiki_schema_lookup", …_search, …_neighbors, …_sources
  ```
  `ingest-ddl --changed` with no explicit paths uses the sources' declared `ddl_paths` (added to
  `SchemaSourceConfig` as `ddl_paths: list[str] = []`) intersected with the files changed by the
  merge; it is a silent no-op when no source declares DDL paths.

### Module 5: MCP Tools, Toolkit and Overlay Mount
- **Path**: `knowledge/wiki/schema/{tools,toolkit}.py` (new); modifies `knowledge/wiki/mcp_server.py` (:178–:200, :226)
- **Responsibility**: four read tools; agent toolkit; read-only `schema` overlay next to the ledger.
- **Depends on**: M2 (read API). **Sequence after FEAT-569 TASK-3358 (`build_wiki_tools`) if it has merged; otherwise rebase.**
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/schema/tools.py  (new — mirrors structural/tools.py:105–225)
  class SchemaLookupInput(BaseModel):     ref: str
  class SchemaSearchInput(BaseModel):     query: str; limit: int = 20
  class SchemaNeighborsInput(BaseModel):  ref: str; depth: int = 1
  class SchemaSourcesInput(BaseModel):    pass
  class WikiSchemaLookupTool(AbstractTool):     name = "wiki_schema_lookup"     # AbstractTool verified: tools.py:24 import
  class WikiSchemaSearchTool(AbstractTool):     name = "wiki_schema_search"
  class WikiSchemaNeighborsTool(AbstractTool):  name = "wiki_schema_neighbors"
  class WikiSchemaSourcesTool(AbstractTool):    name = "wiki_schema_sources"
  def create_schema_tools(store: BaseWikiStore, root: Path | None, config: WikiProjectConfig,
                          service: SchemaPlaneService | None = None) -> list[AbstractTool]:
      """Return [] when no plane is available (mirrors create_structural_tools signature, verified: structural/tools.py:225)."""

  # knowledge/wiki/schema/toolkit.py  (new)
  class SchemaPlaneToolkit(AbstractToolkit):
      """Wraps the four read tools for any ai-parrot agent; tool_prefix='schema'."""
      def __init__(self, service: SchemaPlaneService, **kwargs) -> None: ...

  # knowledge/wiki/mcp_server.py  (modifies)
  #   after :178 ledger block: `schema_service = SchemaPlaneService.from_root(root)` guarded by the same
  #   `find_shared_root(root) is not None` check AND `config.schema.enabled` AND plane dir exists;
  #   handles.append(NamespaceHandle(name="schema", store=schema_service.store,
  #       config=WikiNamespaceConfig(store=str(schema_dir), description="SQL schema plane (sources, schemas, tables)",
  #                                  weight=0.5, overlay_prefixes=["source", "schema", "table"]),
  #       storage_dir=schema_dir, read_only=True))          # NamespaceHandle verified: federation.py:96
  #   after :226 `tools = tools + decision_tools`: `tools = tools + create_schema_tools(read_store, root, config, schema_service)`
  ```

### Module 6: Database Runtime Tier and Read-Repair
- **Path**: modifies `bots/database/cache.py`, `bots/database/toolkits/base.py`, `bots/database/toolkits/sql.py`, `bots/database/agent.py`
- **Responsibility**: plane tier + write-through in `CachePartition`; `origin` on the toolkit config; warm-from-plane; error-driven repair; plane-aware `validate_query` / `generate_query`.
- **Depends on**: M1 (`SchemaPlaneReader` protocol lives in `schema/service.py` but is imported lazily / typed via `TYPE_CHECKING` so `bots/database` gains no hard wiki import), M2.
- **Interface Skeleton**:
  ```python
  # bots/database/toolkits/base.py  (modifies :55)
  class DatabaseToolkitConfig(BaseModel):
      database_type: str = Field(default="postgresql")                          # verified: base.py:55
      origin: Optional[str] = Field(default=None, description="Schema-plane origin alias; defaults to database_type")

  # bots/database/cache.py  (modifies :73–:92, :149, :185)
  class CachePartition:
      def __init__(self, ..., vector_store: Optional["AbstractStore"] = None, ttl_by_completeness=None,
                   plane: Optional["SchemaPlaneReader"] = None, plane_write: bool = False, origin: Optional[str] = None) -> None:
          """New kwargs are optional; when plane is None every code path is unchanged (parity gate, §5)."""
      async def get(...):
          """Tier 2b (NEW, between Redis and the vector store): metadata = await self.plane.get_table(self.origin, schema, table)
          — populates hot_cache like the other tiers. verified anchor: cache.py:149 `# Tier 3: Vector store (point lookup)`."""
      async def store_table_metadata(self, metadata: TableMetadata) -> None:
          """After existing tiers: if self.plane and self.plane_write: await self.plane.put_table(self.origin, self.dialect, metadata).
          verified: cache.py:185."""

  # bots/database/toolkits/sql.py  (modifies :349, :534, :576)
  class SQLToolkit(DatabaseToolkit):
      async def _repair_from_error(self, query: str, err: Exception) -> None:
          """On a retryable schema error (handler._is_retryable_error, verified sql.py:349), describe_table the tables referenced
          by `query` (same regex as validate_query, sql.py:522) and store_table_metadata → write-through. Never raises."""
      async def validate_query(self, sql: str) -> Dict[str, Any]:
          """Message becomes "Table '<s>.<t>' not found in schema plane or cache." when cache_partition.plane is set (verified :534)."""
      async def _warm_table_cache(self) -> None:
          """Prefer cache_partition.plane.get_table over the database for each configured table; fall back to introspection (verified :576)."""
      async def generate_query(...):
          """When the partition has a plane, schema context includes FK join paths from plane.neighbors(depth=1) for target_tables."""

  # bots/database/agent.py  (modifies :145, :206–:224)
  class DatabaseAgent:
      def __init__(self, ..., schema_plane: "SchemaPlaneService | Path | None" = None) -> None:
          """Path → SchemaPlaneService.from_dir(path, read_only=False); stored as self._schema_plane."""
      # in the toolkit loop (verified :206): origin = tk.config.origin or tk.database_type;
      #   CachePartitionConfig(**config_kwargs) unchanged; partition.plane = self._schema_plane; partition.origin = origin;
      #   partition.plane_write = True when schema_plane is set. tk_id is NOT changed.
  ```

### Module 7: Dev-Loop Research Context
- **Path**: modifies `flows/dev_loop/wiki_search.py` (:140)
- **Responsibility**: fold `table:` hits into `build_research_context` when the query names tables/models, best-effort like the ledger fold.
- **Depends on**: M5 (plane mounted in the federated read store).
- **Interface Skeleton**:
  ```python
  # flows/dev_loop/wiki_search.py  (modifies :140 — next to `_get_ledger_context`)
  class DevLoopWikiSearch:
      async def _get_schema_context(self, query: str, max_tokens: int) -> Optional[str]:
          """search_fts(query, category="table") on the federated store; returns "## Related Tables" block or None. Best-effort."""
  ```

### Module 8: Documentation
- **Path**: `docs/wiki/schema-plane.md` (new); modifies `CLAUDE.md` (Codebase Knowledge Graph section: one paragraph on `wiki_schema_*`).
- **Responsibility**: operator guide (declare source, sync, ingest-ddl, diff, lookup, annotate), id grammar, merge rule, security invariants.
- **Depends on**: M4, M5.

---

## 4. Test Specification

Tests live under `packages/ai-parrot/tests/knowledge/wiki/schema/` and `packages/ai-parrot/tests/bots/database/`
(inside a worktree run with `PYTHONPATH=packages/ai-parrot/src`).

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_table_concept_id_roundtrip` | M1 | `parse_table_id(table_concept_id(o,s,t)) == (o,s,t)`; other kinds raise `ValueError` |
| `test_normalize_ref_forms` | M1 | `table:…`, bare `o:s.t`, `s.t` unique → id; `s.t` ambiguous → candidate list |
| `test_content_hash_ignores_volatile` | M1 | changing `row_count`/`loaded_at` keeps the hash; changing a column type changes it |
| `test_render_ddl_per_dialect` | M1 | postgres vs bigquery output for one `TableMetadata`; byte-stable across two renders |
| `test_render_page_edges_and_columns` | M1 | `contains`/`references`/`defined_in` edges, `fk_target` populated, `source_id="schema:<origin>"` |
| `test_schema_store_columns_side_table` | M1 | `upsert_columns` replace semantics; `find_columns(fk_target_prefix=…)`; `replace_schema_slice` removes columns of dropped tables |
| `test_schema_plane_config_defaults` | M1 | `WikiProjectConfig().schema.enabled is True`, `schema_path(root) == root/.parrot/schema`; existing `wiki.json` without `schema` still loads |
| `test_metadata_source_accepts_ddl` | M1 | `TableMetadata(source="ddl")` validates |
| `test_service_from_root_and_from_dir` | M2 | both open `schema.db`; `from_dir(read_only=True)` refuses writes with `PermissionError` |
| `test_sync_writes_slice_and_report` | M2 | fake toolkit → pages/columns/edges; `SyncReport` created/updated/unchanged; partial failure keeps the old page and reports it |
| `test_sync_changed_only_rewrites_drift` | M2 | second sync with one changed column rewrites exactly one page |
| `test_sync_preserves_memory_annotations` | M2 | `mem-*` page linked `about` a table survives `sync`; dropped table leaves a dangling edge, not a deleted note |
| `test_lookup_age_and_stale` | M2 | `stale` true past `stale_after_days[completeness]` |
| `test_neighbors_join_paths_with_column_pair` | M2 | depth 2 walk returns `(src_col → dst_col)` per hop |
| `test_split_statements_isolates_parse_error` | M3 | a file with one bad statement still yields its other `CREATE TABLE`s (regression for F025's 6 failing files) |
| `test_fold_ddl_inline_primary_key` | M3 | `id SERIAL PRIMARY KEY` → `primary_keys == ["id"]` |
| `test_fold_ddl_alter_sequence` | M3 | `ALTER TABLE … ADD COLUMN` folded in file-name order |
| `test_fold_ddl_corpus_fixture` | M3 | `tools/working_memory/task_memory/migrations/001_task_memory.sql` → 6 tables, 70 columns, 3 FKs |
| `test_ingest_ddl_merge_rule_live_wins` | M3 | live page present → only `defined_in` added; absent → `source="ddl"` page created |
| `test_diff_reports_divergence` | M3 | column type mismatch listed; identical → empty |
| `test_cli_schema_group_registered` | M4 | `wikitoolkit schema --help` lists six verbs |
| `test_cli_write_verbs_refuse_linked_worktree` | M4 | `sync`/`ingest-ddl`/`diff --ledger` exit non-zero with the worktree message |
| `test_git_hook_block_contains_schema_ingest` | M4 | hook text has the ingest-ddl line **inside** the `if [ ! -f .git ]` guard |
| `test_permissions_include_schema_tools` | M4 | four `mcp__wikitoolkit__wiki_schema_*` entries present |
| `test_schema_tools_round_trip` | M5 | each tool over an in-memory plane; `lookup` accepts bare `o:s.t` |
| `test_schema_toolkit_exposes_four_tools` | M5 | `SchemaPlaneToolkit.get_tools()` names |
| `test_mcp_mounts_schema_overlay_when_present` | M5 | `create_wiki_mcp_server` adds a `schema` handle + 4 tools when plane dir exists; tool count unchanged when absent |
| `test_federation_two_overlays_cross_kind` | M5 | ledger + schema overlays: `wiki_related("table:x/a.b")` and `wiki_related("sym:m.py#Model")` hydrate across the boundary (brainstorm spike 2) |
| `test_cache_partition_plane_tier_order` | M6 | miss in LRU/Redis → plane hit → hot_cache populated; vector store not consulted |
| `test_cache_partition_write_through_flag` | M6 | `plane_write=False` never calls `put_table`; `True` does |
| `test_cache_partition_parity_without_plane` | M6 | existing `test_cache.py` suite passes unchanged with `plane=None` |
| `test_toolkit_config_origin_default` | M6 | `origin is None` → agent uses `database_type` |
| `test_sql_repair_from_error_writes_through` | M6 | simulated `relation does not exist` → `describe_table` for referenced tables → `put_table` |
| `test_validate_query_wording_with_plane` | M6 | message says "schema plane or cache" only when a plane is set |
| `test_warm_table_cache_prefers_plane` | M6 | database `describe_table` not called for tables present in the plane |
| `test_devloop_schema_context_best_effort` | M7 | absent plane → research context unchanged; present → `## Related Tables` appended |

### Integration Tests
| Test | Description |
|---|---|
| `test_ingest_ddl_then_lookup_via_mcp` | ingest the in-repo `001_task_memory.sql` into a temp plane, mount via `create_wiki_mcp_server`, `wiki_schema_lookup("taskmem:public.<table>")` returns DDL + columns + `defined_in` edge to the `file:` page |
| `test_live_sync_sqlite_source` | `SQLToolkit(database_type="sqlite")` against a temp SQLite DB → `sync` → `lookup` → `neighbors`; then `DatabaseAgent`-style `CachePartition(plane=…)` warm reads without touching the DB |
| `test_bots_database_suite_plane_on_off` | run `packages/ai-parrot/tests/bots/database/` with an in-memory plane injected and without — both green (brainstorm spike 4) |

### Test Data / Fixtures
```python
@pytest.fixture
def plane_dir(tmp_path) -> Path: return tmp_path / ".parrot" / "schema"

@pytest.fixture
def schema_service(plane_dir) -> SchemaPlaneService:
    return SchemaPlaneService.from_dir(plane_dir, config=SchemaPlaneConfig(), read_only=False)

@pytest.fixture
def sales_metadata() -> TableMetadata:
    """epson.sales with store_id FK → epson.stores(id); completeness FULL, source 'information_schema'."""

@pytest.fixture
def fake_sql_toolkit(sales_metadata) -> SQLToolkit:
    """describe_table returns sales_metadata; execute_query raises 'relation does not exist' on demand."""

DDL_CORPUS = Path("packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql")
```

---

## 5. Acceptance Criteria

- [ ] AC1 — `wikitoolkit schema add-source bigquery --dialect bigquery --dsn-env EPSON_BQ_DSN --schemas epson` writes `schema.sources.bigquery` into `.parrot/wiki.json` with the env **name** only; `grep -r "<dsn value>" .parrot/` finds nothing after a sync (G7).
- [ ] AC2 — `wikitoolkit schema sync <origin>` creates `source:`/`schema:`/`table:` pages under `.parrot/schema/schema.db`; ids match `table:<origin>/<schema>.<table>`; `--changed` on an unchanged database reports `unchanged == all` and rewrites nothing (G1, G2, G4).
- [ ] AC3 — `wiki_schema_lookup("bigquery:epson.sales")` and `wiki_schema_lookup("table:bigquery/epson.sales")` return the same `LookupResult`; an ambiguous `epson.sales` returns candidates, never a guess (G2).
- [ ] AC4 — `wikitoolkit schema ingest-ddl <paths> --origin o --dialect postgres` over the 32 in-repo `.sql` files completes with exit 0, recovers ≥ 20 `CREATE TABLE`s and ≥ 329 columns, and reports each unparseable **statement** (not file) in `parse_errors` (G3; F025 baseline).
- [ ] AC5 — For one origin with both producers, a live page is never overwritten by DDL facts; `defined_in` edges are present on every table that has a migration; `schema diff` lists the divergences (merge rule).
- [ ] AC6 — `wiki_related("table:x/a.b")` and `wiki_related("sym:m.py#Model")` both hydrate across the schema overlay boundary with the ledger overlay mounted at the same time (spike 2).
- [ ] AC7 — `wiki_remember(fact, link_page_id="table:…", rel="about")` followed by `schema sync` keeps the note and it appears in the next `wiki_schema_lookup` (G6).
- [ ] AC8 — `CachePartition(plane=None)` behaviour is unchanged: the pre-existing `packages/ai-parrot/tests/bots/database/` suite passes with no modification; with a plane, a miss in LRU/Redis is served from the plane before the vector store (G5).
- [ ] AC9 — A `relation does not exist` error in `SQLToolkit.execute_query` triggers `describe_table` for the referenced tables and a plane write-through; no full `information_schema` scan runs on the request path (G4).
- [ ] AC10 — `sync`, `ingest-ddl` and `diff --ledger` refuse to run inside a linked worktree with an explicit message; the post-merge hook's ingest line sits inside the existing `[ ! -f .git ]` guard.
- [ ] AC11 — `create_wiki_mcp_server` on a project without a plane mounts no `schema` namespace and exposes no `wiki_schema_*` tools (tool count unchanged); with a plane it exposes exactly four.
- [ ] AC12 — `SchemaPlaneService.from_dir(dir)` opens a plane with no git root; `DatabaseAgent(schema_plane=Path)` warms toolkits from it without a repository (G8).
- [ ] AC13 — `MetadataSource` accepts `"ddl"`; `bots/database` gains no import-time dependency on `parrot.knowledge.wiki` (checked by a test that imports `parrot.bots.database.cache` with `parrot.knowledge.wiki` blocked in `sys.modules`).
- [ ] AC14 — `ruff check` and `black --check` clean on every touched file; all §4 tests pass.
- [ ] AC15 — `docs/wiki/schema-plane.md` documents id grammar, merge rule, security invariants and the six CLI verbs.

---

## 6. Codebase Contract

> Verified against commit `4cb7286a8` (dev, 2026-09-24). Paths relative to
> `packages/ai-parrot/src/parrot/` unless noted. Finding ids reference `sdd/state/FEAT-600/findings/`.

### Verified Imports
```python
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, BaseWikiStore   # store.py:855, :409, :525
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle          # federation.py:638 (__init__), :96
from parrot.knowledge.wiki.project import (WikiNamespaceConfig, WikiProjectConfig, find_shared_root,
                                           is_linked_worktree, load_effective_config, sqlite_policy_from_config,
                                           wiki_write_lock)                                # project.py:183, :381, :1197, :1185, :910, :695, :73
from parrot.knowledge.wiki.ledger.store import LedgerStore                                 # ledger/store.py:24
from parrot.knowledge.wiki.ledger.service import LedgerService                             # ledger/service.py (from_root :116)
from parrot.knowledge.wiki.symbols import SymbolRecord, sym_concept_id, parse_sym_id, symbol_to_page_fields  # symbols.py:56, :141, :159, :190
from parrot.knowledge.wiki.structural.tools import create_structural_tools                 # structural/tools.py:225
from parrot.knowledge.wiki.tools import create_wiki_tools, WikiRememberTool                # tools.py:807, :336
from parrot.knowledge.wiki.decisions.models import DecisionConfig                          # decisions/models.py:62 (sub-config precedent)
from parrot.tools.abstract import AbstractTool, ToolResult                                 # as used in tools.py:24, structural/tools.py:30
from parrot.bots.database.models import TableMetadata, SchemaMetadata, Completeness, MetadataSource  # models.py:131, :112, :97, :108
from parrot.bots.database.cache import CachePartition, CachePartitionConfig, CacheManager  # cache.py:54, :33, :612
from parrot.bots.database.toolkits.base import DatabaseToolkit, DatabaseToolkitConfig      # toolkits/base.py:78, :31
from parrot.bots.database.toolkits.sql import SQLToolkit, _SQLGLOT_DIALECT_MAP             # toolkits/sql.py:62, :45
from parrot.bots.database.toolkits.postgres import PostgresToolkit                         # toolkits/postgres.py:28
from parrot.bots.database.toolkits.bigquery import BigQueryToolkit                         # toolkits/bigquery.py:19
from parrot.bots.database.retries import SQLRetryHandler                                   # retries.py:123
import sqlglot; from sqlglot import exp                                                    # pyproject.toml:182 "sqlglot>=20.0"; installed 30.18.0
```

### Existing Class Signatures
```python
# knowledge/wiki/store.py
class WikiPageRecord(BaseModel):            # :409 — concept_id, node_id, title, category="concept", summary, body,
                                            #   source_id, token_count, origin="ingest", asserted_by, updated_at, content_hash
class BaseWikiStore(ABC):                   # :525
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int                              # :544
    async def add_edges(self, edges: list[tuple]) -> int                                          # :547 ((src,dst,rel[,provenance]))
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord],
                                   edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]   # :550
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]      # :565
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict]  # :576
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict]  # :582
    async def upsert_symbols(self, symbols: list[SymbolRecord], source_id: Optional[str] = None) -> int    # :721
    async def find_symbols(self, name=None, qualname_prefix=None, kind=None, language=None, path_prefix=None, limit=50)  # :768
    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]                # :837
class SQLiteWikiStore(BaseWikiStore):       # :855
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False,
                 sqlite_policy: SQLitePragmaPolicy | None = None, persistent_writer: bool = False)  # :903
    # edges DDL :112-120 — src, dst, rel DEFAULT 'references', provenance DEFAULT 'extracted', PK (src,dst,rel)
    # symbols DDL :131 — side-table precedent
    async def _write(self, operation: str)  # async context manager yielding an aiosqlite connection (used by LedgerStore.ledger_transaction)

# knowledge/wiki/federation.py
@dataclass class NamespaceHandle:           # :95-96 — name, store, config, origin, storage_dir, read_only
class FederatedWikiStore(BaseWikiStore):
    def __init__(self, local, local_name="local", handles=None, skipped=None, *, qualify_local=False, origin_local=None)  # :638
    def _route(self, page_id) -> tuple[NamespaceHandle | None, str, bool]                          # :885
    def _route_bare_overlay_id(self, page_id) -> str | None                                        # :917 (kind prefix → overlay)
    async def neighbors(self, concept_id, rel=None, direction="both")                              # :976-1059 (3 layers)

# knowledge/wiki/project.py
class WikiNamespaceConfig(BaseModel):       # :183 — exactly one of path/store/database/vault; overlay_prefixes :240
class WikiProjectConfig(BaseModel):         # :381 — backend: Literal["sqlite","memory","arangodb"] :419; decisions: DecisionConfig :478
    def ledger_path(self, root: Path) -> Path   # :520  → root/.parrot/ledger
    def storage_path(self, root: Path) -> Path  # :532
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]                       # :73
def sqlite_policy_from_config(config) -> SQLitePragmaPolicy                                        # :695
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig               # :910 (.config → WikiProjectConfig)
def is_linked_worktree(git_dir: Path) -> bool                                                      # :1185 (git_dir.is_file())
def find_shared_root(start: Path | None = None) -> Path | None                                     # :1197

# knowledge/wiki/ledger/store.py / service.py
class LedgerStore(SQLiteWikiStore): __init__(db_path, wiki_name="", *, read_only=False, sqlite_policy=None, persistent_writer=False)  # :24
class LedgerService:
    @classmethod def from_root(cls, root: Path | None = None) -> "LedgerService"                   # :116-143 (template)

# knowledge/wiki/structural/service.py
class StructuralService: async def _ensure_fresh(self, rel_paths: list[str]) -> list[str]          # :431-479 (read-repair shape)

# knowledge/wiki/claude_code/assets.py
def git_hook_block(root: Path) -> str       # :166-190; upsert line :187; permission list entries :60-62

# knowledge/wiki/cli.py
@click.group(name="wiki") def wiki()        # :1374
@wiki.group(name="ledger") def ledger()     # :2764  (groups: symbols :2277, ns :2479, ledger :2765, sync :3958)

# knowledge/wiki/mcp_server.py — create_wiki_mcp_server
#   ledger init guard :154-171 (find_shared_root(root) is not None); mount block :178-198;
#   `if handles or skipped: read_store = FederatedWikiStore(...)` :200-201; create_wiki_tools :202;
#   structural tools :208-211; decision tools :223-226 (`tools = tools + decision_tools`)

# bots/database/models.py
class Completeness(IntEnum)                 # :97  NAME_ONLY=1, WITH_COLUMNS=2, FULL=3
MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "unknown"]              # :108
@dataclass class SchemaMetadata             # :112
@dataclass class TableMetadata              # :131 — schema, tablename, table_type, full_name, comment, columns, primary_keys,
                                            #   foreign_keys: List[Dict] :140, indexes, row_count :142, sample_data :143,
                                            #   unique_constraints, last_accessed, access_frequency, avg_query_time,
                                            #   completeness=FULL :153, loaded_at, source="unknown" :155; .satisfies(required)

# bots/database/cache.py
class CachePartitionConfig(BaseModel)       # :33 — namespace, lru_maxsize=500, lru_ttl=1800, redis_ttl=3600, ttl_by_completeness :40
class CachePartition:                       # :54
    def __init__(..., lru_ttl=1800, redis_ttl=3600, vector_store=None :73, ttl_by_completeness=None :74)  # hot_cache TTLCache :85; vector_enabled :92
    def _table_cache_key(self, schema_name, table_name) -> str   # :102 → f"table:{schema}:{table}" :104
    async def get(self, schema_name, table_name, *, required=Completeness.NAME_ONLY, max_age=None) -> Optional[TableMetadata]  # :112
        # Tier 1 LRU → 1b schema_cache → 2 _get_from_redis (:512) → 3 _search_vector_store (:543, anchor :149) → completeness/age gates
    async def store_table_metadata(self, metadata: TableMetadata) -> None                          # :185
class CacheManager: def create_partition(self, config: CachePartitionConfig) -> CachePartition     # :612 / :656

# bots/database/toolkits/base.py
class DatabaseToolkitConfig(BaseModel)      # :31 — dsn :34, allowed_schemas :35, primary_schema :36, tables :37, read_only :45, database_type :55
class DatabaseToolkit(AbstractToolkit, ABC) # :78 — __init__(..., cache_partition: Optional[CachePartition] = None :111); self.cache_partition :141

# bots/database/toolkits/sql.py
_SQLGLOT_DIALECT_MAP: Dict[str, str]        # :45-59 postgresql/postgres→postgres, bigquery, mysql/mariadb→mysql, sqlite, mssql/sqlserver→tsql, oracle, clickhouse, duckdb, redshift, snowflake
class SQLToolkit(DatabaseToolkit):          # :62; _metadata_source="information_schema" :80
    async def search_schema(...)            # :113
    async def describe_table(self, schema, table) -> Optional[TableMetadata]   # :183 (cache first, FULL introspection on miss)
    async def generate_query(self, natural_language, target_tables=None, query_type="SELECT") -> str   # :214
    async def execute_query(...)            # :283; retry path builds SQLRetryHandler(toolkit=self, config=retry_cfg) :349
    async def validate_query(self, sql) -> Dict[str, Any]   # :509; "not found in cache." :534
    async def _warm_table_cache(self) -> None               # :576
    def _get_information_schema_query(...) :636; _get_columns_query :672; _get_primary_keys_query :691; _get_unique_constraints_query :714
class PostgresToolkit(SQLToolkit)           # postgres.py:28; _metadata_source="pg_catalog" :41; overrides _get_information_schema_query :123
class BigQueryToolkit(SQLToolkit)           # bigquery.py:19; overrides _get_information_schema_query :60

# bots/database/agent.py — DatabaseAgent
#   __init__ :126; self.cache_manager = CacheManager(redis_url=..., vector_store=...) :145
#   toolkit loop :205-224: tk_id = f"{tk.database_type}_{tk.primary_schema}" :206; create_partition :221; register_database :224

# bots/database/retries.py
#   retry_on_errors includes "column does not exist", "relation does not exist" :56-57; SQLRetryHandler :123 (_is_retryable_error, _extract_table_column_from_error, _get_sample_data_for_error :135)

# flows/dev_loop/wiki_search.py
class DevLoopWikiSearch:
    def __init__(self, *, store, wiki_name, shared_root=None)                                       # :33
    async def build_research_context(self, query, budget_tokens=_DEFAULT_BUDGET_TOKENS) -> Optional[str]  # :101; ledger fold :139-148
    async def _get_ledger_context(self, query, max_tokens) -> Optional[str]                        # :158 (pattern for _get_schema_context)

# knowledge/wiki/file_suffixes.py — ".sql" :38 (repo_scan already emits file: pages for migrations)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SchemaStore` | `SQLiteWikiStore.__init__` / `_write()` / `replace_source_slice` | subclass | `store.py:855, :903, :1614` |
| `SchemaPlaneService.from_root` | `find_shared_root`, `load_effective_config`, `sqlite_policy_from_config` | same calls as `LedgerService.from_root` | `ledger/service.py:116-143` |
| `schema` overlay | `NamespaceHandle`, `FederatedWikiStore` | `handles.append(...)` before `FederatedWikiStore(...)` | `mcp_server.py:178-201` |
| `create_schema_tools` | tool list | `tools = tools + ...` after decision tools | `mcp_server.py:226` |
| `WikiProjectConfig.schema` | Pydantic sub-model | field after `decisions` | `project.py:478` |
| live producer | `SQLToolkit.describe_table` | per-table call | `sql.py:183` |
| DDL producer | `sqlglot.parse_one` / `exp.*` | new usage (no precedent in repo) | `security/query_validator.py:246` lists `exp.Create` as forbidden in *queries* only |
| `defined_in` edges | `file:` pages | `file_concept_id(rel_path)` | `symbols.py` / `structural/service.py:431` usage |
| plane tier | `CachePartition.get` | new tier before `_search_vector_store` | `cache.py:149` |
| write-through | `CachePartition.store_table_metadata` | append | `cache.py:185` |
| repair hook | `SQLToolkit.execute_query` retry branch | call after `handler._is_retryable_error(err)` | `sql.py:349` |
| `origin` | `DatabaseToolkitConfig` | new field | `toolkits/base.py:55` |
| agent wiring | `DatabaseAgent` toolkit loop | set `partition.plane/origin/plane_write` | `agent.py:206-224` |
| hook line | `git_hook_block` | inside `if [ ! -f .git ]` | `assets.py:187` |
| dev-loop | `build_research_context` | fold next to `_get_ledger_context` | `wiki_search.py:140` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.knowledge.wiki.schema` package, `SchemaStore`, `SchemaPlaneService`, `SchemaPlaneToolkit`, `create_schema_tools`, any `wiki_schema_*` tool, `wikitoolkit schema` group~~ — all new (F019, F021).
- ~~`table:` / `schema:` / `source:` page kinds or overlay prefixes~~ — none declared anywhere; the literal `table:` exists only as the `CachePartition` **Redis key** prefix (`cache.py:104`), the `table:read` permission string (`auth/dataplane_guard.py:182`) and a regex in `toolkits/_internal.py:272` (F019).
- ~~an `attrs` / payload column on `edges`~~ — edges are `(src, dst, rel, provenance)` only (F003).
- ~~`LedgerService.from_dir()`, `StructuralService(read_repair=False)`~~ — **not merged yet**; they are FEAT-569 TASK-3354 / TASK-3353 (in progress). Do not import them; implement `SchemaPlaneService.from_dir` independently (F023).
- ~~`WikiProjectConfig.backend == "postgres"`~~ — the Literal stops at `arangodb` (`project.py:419`) (F004).
- ~~`MetadataSource` value `"ddl"`; `origin` / `dialect` fields on `TableMetadata`~~ — added by M1 (`"ddl"`) and carried by `TableRecord` (origin/dialect), never on `TableMetadata` (F006).
- ~~any `sqlglot` DDL folding (`exp.ColumnDef`, `exp.ForeignKey`, `exp.PrimaryKey` handling)~~ — zero occurrences; `exp.Create` appears once in a *blocklist* (F018).
- ~~`DatabaseToolkitConfig.origin`, `CachePartition.plane`, `plane_write`, a durable tier~~ — tiers are LRU / schema cache / Redis / vector store (F007, F009).
- ~~`_internal.generate_create_table_statement(TableMetadata)`~~ — it is a **method taking YAML text** (`_internal.py:278`); not a renderer to reuse (F008).
- ~~a single `TableMetadata`~~ — a **legacy duplicate** exists at `packages/ai-parrot-tools/src/parrot_tools/database/models.py:31` without `completeness`/`source`; never import it in plane code (F022).
- ~~hooks running anything schema-related~~ — `post-commit`/`post-merge` run `upsert --changed --quiet` only (F012).
- ~~`SQLQuerySource.prefetch_schema` returning a schema~~ — returns `{}` (F011).
- ~~`DecisionConfig` in `project.py`~~ — it lives in `knowledge/wiki/decisions/models.py:62` and is imported into `project.py`; mirror that layout (`schema/models.py` → imported by `project.py`) and watch for the circular-import trap FEAT-578 hit (`c85837ae4`).

### Edit Sites (Blueprint Anchors)

Verified against: `4cb7286a8`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/ids.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/render.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/live.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/ddl.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/toolkit.py` | CREATE | — | — | — |
| `docs/wiki/schema-plane.md` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `    decisions: DecisionConfig = Field(` | `project.py:478` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `    def ledger_path(self, root: Path) -> Path:` | `project.py:520` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/models.py` | MODIFY | `MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "unknown"]` | `models.py:108` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | `    if ledger_service is not None:` | `mcp_server.py:178` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | `    if handles or skipped:` | `mcp_server.py:200` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | `    tools = tools + decision_tools` | `mcp_server.py:226` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `@wiki.group(name="ledger")` | `cli.py:2764` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `    "mcp__wikitoolkit__wiki_blast_radius",` | `assets.py:62` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `        f"if [ ! -f .git ]; then\n"` (the ingest line is inserted after the following `upsert --changed` line, :187) | `assets.py:186` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py` | MODIFY | `    database_type: str = Field(default="postgresql")` | `base.py:55` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/cache.py` | MODIFY | `        ttl_by_completeness: Optional[Dict[int, int]] = None,` (CachePartition.__init__ kwargs) | `cache.py:74` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/cache.py` | MODIFY | `        self.vector_enabled = vector_store is not None` | `cache.py:92` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/cache.py` | MODIFY | `        # Tier 3: Vector store (point lookup)` | `cache.py:149` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/cache.py` | MODIFY | `    async def store_table_metadata(self, metadata: TableMetadata) -> None:` | `cache.py:185` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | `            handler = SQLRetryHandler(toolkit=self, config=retry_cfg)` | `sql.py:349` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | `                    errors.append(f"Table '{schema}.{table_part}' not found in cache.")` | `sql.py:534` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | `    async def _warm_table_cache(self) -> None:` | `sql.py:576` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | `        self.cache_manager = CacheManager(redis_url=redis_url, vector_store=vector_store)` | `agent.py:145` | 1 |
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | `            tk_id = f"{tk.database_type}_{tk.primary_schema}"` | `agent.py:206` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py` | MODIFY | `            ledger_context = await self._get_ledger_context(query, budget_tokens // 2)` | `wiki_search.py:140` | 1 |
| `CLAUDE.md` | MODIFY | `**Symbol lookup and blast radius (FEAT-498).**` | (paragraph start in "Codebase Knowledge Graph") | 1 |

- `/sdd-task` MUST re-run `grep -c` for every row it uses; `mcp_server.py` and `cli.py` are hot files (F024) and FEAT-569 edits them concurrently.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Ledger plane template** (F001, F005): own SQLite file, `SQLiteWikiStore` subclass, `Service.from_root` via `find_shared_root` + `load_effective_config` (never raw `load_project_config` — a call-site guard test enforces it), read-only `NamespaceHandle` with `overlay_prefixes`, `store=` set only to satisfy the config validator.
- **Kind-first ids** (decided): `table:<origin>/<schema>.<table>`; `normalize_ref` on every input boundary; never guess an ambiguous `schema.table`.
- **Side table** (F003, F013): `columns` mirrors `symbols` (delete-then-insert inside one `_write()`, cleared by the slice replace); FK column pair lives in `columns.fk_target`, the edge stays plain `references`.
- **One record**: the plane stores `parrot.bots.database.models.TableMetadata`; `TableRecord` carries `origin`/`dialect`; producers set `source` (`information_schema` / `pg_catalog` / `ddl`).
- **Merge rule** (decided): live authoritative; DDL fills gaps and adds `defined_in`; `diff` reports.
- **Read-repair shape** (F014): `wiki_write_lock(timeout=0)`, `stale=True` when the lock is busy, repair only the hit tables.
- **Best-effort integration** (F020): plane absent ⇒ every consumer behaves exactly as today; log once.
- **No wiki import inside `bots/database`**: type the plane as a `Protocol` under `TYPE_CHECKING`; `DatabaseAgent` performs the lazy import when `schema_plane` is given (AC13).
- **stdout discipline** in `mcp_server.py`: wrap the new imports in `contextlib.redirect_stdout(sys.stderr)` like the ledger/structural/decision blocks (navconfig settings-init leak).
- Google-style docstrings, strict typing, `black` 120 cols, `ruff` clean; async everywhere; `self.logger`.

### Known Risks / Gotchas
- **FEAT-569 concurrency** (F023, F024): 17 in-progress tasks touch `mcp_server.py`, `cli.py`, tool bundling and add `from_dir()`/`read_repair=False`. M5/M4 land last and rebase onto whichever merges first; the FEAT-569 tool-surface golden test must add the four `wiki_schema_*` names. Do not import FEAT-569 symbols that are not on `dev`.
- **sqlglot whole-file `ParseError`** (F025): 6/32 in-repo files fail as a unit; `split_statements` + per-statement `try` is mandatory. Inline `PRIMARY KEY` is a column constraint, not `exp.PrimaryKey`. PL/pgSQL bodies and `DO $$` fall back to `Command` — skip silently. BigQuery/T-SQL DDL fidelity is untested in-repo (informational).
- **Duplicate `TableMetadata`** (F022): importing `parrot_tools.database.models` silently loses `completeness`/`source`. Test AC13 + an import-path assertion guard it.
- **Redis key prefix `table:`** (F007): same string as the page kind; different store, but log lines should print full page ids to stay unambiguous.
- **Slice replace vs. annotations** (F015): `mem-*` pages have `origin="memory"` and no `source_id`, so `replace_source_slice("schema:<origin>")` leaves them; a dropped table leaves a dangling `about` edge surfaced by `broken_edges()`, never deleted.
- **Cross-origin FKs**: edge to a dangling `table:` id; `neighbors()` already returns dangling targets; `diff` reports them.
- **Alias collision**: `add-source postgres` twice refuses with the existing alias listed.
- **Partial live sync failure**: failing tables keep their previous page, flagged `stale`, listed in `SyncReport.failed`.
- **Lock contention**: the plane never touches `wiki.lock`; it has its own `schema.db` writer lock (SQLite WAL via `sqlite_policy_from_config`).
- **Circular import trap** (FEAT-578 `c85837ae4`): `project.py` importing `schema/models.py` must not pull `store.py`/`sqlglot` at import time — keep `schema/models.py` dependency-free (Pydantic + `bots.database.models` only).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `sqlglot` | `>=20.0` (installed 30.18.0) | DDL parse + canonical DDL render — already a core dependency |
| `aiosqlite` | existing | `schema.db` via `SQLiteWikiStore` |
| `asyncdb` (`pg`, `bigquery`, …) | existing | live introspection through the existing toolkits |
| `click` | existing | `wikitoolkit schema` group |

---

## 8. Open Questions

- [x] **Id grammar** — *Resolved in brainstorm*: kind-first `table:<origin>/<schema>.<table>`; `normalize_ref()` accepts bare `bigquery:epson.sales` on input. (→ §2 Overview, M1 `ids.py`, AC3)
- [x] **Origin = alias or `tk_id`?** — *Resolved in brainstorm*: alias, declared explicitly via `DatabaseToolkitConfig.origin` defaulting to `database_type`; `tk_id` untouched. (→ M6, AC8)
- [x] **Columns as pages?** — *Resolved in brainstorm*: side table in v1. (→ M1 `SchemaStore.COLUMNS_DDL`)
- [x] **FK edge payload** — *Resolved in brainstorm*: no edge attribute in v1; plain `references` edge, column pair in `columns.fk_target`; `attrs` deferred. (→ §2, M1 `render_page`, M2 `neighbors`)
- [x] **Live vs. DDL merge rule** — *Resolved in brainstorm*: live authoritative; DDL fills live-absent tables and adds `defined_in`; `diff` reports, never timestamp-resolved. (→ M3 `ingest_ddl`, AC5)
- [x] **Where the plane lives in production** — *Resolved in brainstorm*: v1 SQLite `schema.db` with `from_root` + `from_dir`; postgres/arangodb plane after FEAT-569. (→ M2, AC12, Non-Goals)
- [x] **`maps_to` extraction** — *Resolved in brainstorm*: v2. (→ Non-Goals)
- [x] **Schema history** — *Resolved in brainstorm*: no archive in v1; `diff` is the change report. (→ Non-Goals)
- [x] **Exposure to non-Claude agents** — *Resolved in brainstorm*: `SchemaPlaneToolkit` only; `prefetch_schema` / `dq_get_table_metadata` follow-ups. (→ M5, Non-Goals)
- [ ] **Q1 — `ingest-ddl --changed` path discovery**: the spec adds `ddl_paths` to `SchemaSourceConfig` so the post-merge hook knows which `.sql` files belong to which origin. Confirm, or prefer a top-level `schema.ddl` map in `wiki.json`. Decide during `/sdd-task` (M4). — *Owner: Jesus*
- [ ] **Q2 — BigQuery cost baseline (brainstorm spike 3)**: bytes billed for `BigQueryToolkit.describe_table` (FULL) over the Epson dataset vs. plane reads — a measurement task, not a design blocker; needs credentials. — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` (not run) · **Status: skipped (exploration doc not `accepted` — brainstorm status is
> `resolved`, proposal status is `review`; §3b precondition requires `accepted`)** · Transcript: none.
> To run it: set `status: accepted` on `sdd/proposals/sql-schema-plane.proposal.md` and re-run `/sdd-spec FEAT-600`
> (the spec will be reused, not re-reserved).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-600 (`.claude/worktrees/feat-FEAT-600-sql-schema-plane`, from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in parentheses):
  - M2 → M1 (imports `SchemaStore`, `TableRecord`, `render_page`, `SchemaPlaneConfig`)
  - M3 → M1, M2 (extends `SchemaPlaneService`; folds into `TableRecord`)
  - M4 → M2, M3 (CLI verbs call `sync` / `ingest_ddl` / `diff` / `lookup`)
  - M5 → M2 (tools call the read API; mount opens `SchemaPlaneService.from_root`)
  - M6 → M1, M2 (`SchemaPlaneReader` protocol + `from_dir`; `MetadataSource` literal)
  - M7 → M5 (needs the overlay mounted in the federated read store)
  - M8 → M4, M5 (documents the CLI and tools)
  - No edge between M3 and M5/M6, or between M4 and M6 — those pairs run concurrently.
- **Shared files** (tasks serialized): `knowledge/wiki/schema/service.py` (M2 creates, M3 extends); `knowledge/wiki/claude_code/assets.py` (M4 only, two anchors); `bots/database/toolkits/sql.py` (M6 only, three anchors). Nothing else is touched by two modules.
- **Exclusive resources**: none (no extension rebuild, no lockfile, no DB migration; `.parrot/wiki.json` schema change is additive with defaults).
- **Cross-feature dependencies**: none blocking. **Coordination**: FEAT-569 `wikitoolkit-http-mcp` (in progress) edits `mcp_server.py`, `cli.py`, tool bundling; M4/M5 rebase onto it if it merges first and its tool-surface golden test gains the four `wiki_schema_*` tools.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-24 | Jesus Lara / Claude | Initial draft from brainstorm Option B + FEAT-600 proposal (all brainstorm questions resolved) |
