---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Schema Plane — SQL data-model knowledge on the LLM Wiki plane

**Date**: 2026-09-24
**Author**: Jesus Lara (drafted with Claude)
**Status**: resolved — open questions closed 2026-09-24; see FEAT-600 proposal
**Recommended Option**: B
**Related**: `claude/ast-grep-structural-plane-design.md` (FEAT-498, `sym:` pages, read-repair), `claude/sdd-work-ledger.brainstorm.md` (FEAT-566, overlay namespace pattern), `bots/database/` (FEAT-062/082/172 — `SQLToolkit`, `CachePartition`)

---

## Problem Statement

Every agent that touches a relational source re-discovers the data model at run time. `SQLToolkit.describe_table` / `search_schema` go to `information_schema` (or `pg_catalog` / BigQuery `INFORMATION_SCHEMA`) whenever the `CachePartition` misses, and the partition is a **TTL cache** (LRU 30 min, Redis 1 h, capped further by `ttl_by_completeness`): it is per process or per Redis, private to `DatabaseAgent`, and empty on every cold start (`_warm_table_cache` fills it by hitting the database again). Concretely:

1. **No durable, shared knowledge of the data model.** The same `TableMetadata` (columns, PKs, FKs, indexes, comments) is introspected over and over — per agent instance, per deploy, per environment. On BigQuery (the Epson price-freshness case) `INFORMATION_SCHEMA` reads are billed and rate-limited; on Postgres they are cheap but still a round-trip per miss.
2. **Coding agents have no data model at all.** An `sdd-coder` writing a repository, a `DatabaseToolkit` subclass, a Flowtask step or a `DatasetManager` source has no database connection inside the worktree and no page to read. `wikitoolkit mcp` exposes `file:` / `sym:` / `issue:` / `decision` pages, nothing about tables. `SQLQuerySource.prefetch_schema()` in `dataset_manager/sources/sql.py` literally returns `{}` ("schema only available after first fetch").
3. **Relations are not a graph.** `TableMetadata.foreign_keys` is a list inside one entry; "what joins to `epson.sales`?", "which tables does this view depend on?", "which Python model maps to this table?" cannot be asked. Join-path discovery is the single most useful thing for text-to-SQL and it is exactly what `information_schema` gives worst.
4. **No place for meaning.** `information_schema` will never say "`store_id` here is the T-ROC store id, not the Epson one" or "`sales_v1` is deprecated, use `sales`". Today that lives in prompts (`bots/database/prompts.py`) or nowhere. `wiki_remember` exists but has no table to point at.

Who is affected: `DatabaseAgent` and its `SQLToolkit` / `PostgresToolkit` / `BigQueryToolkit` (runtime), `sdd-coder` / `dev_loop` research node (development), `DatasetManager` SQL sources, and the Epson pipeline (`DatabaseToolkit` export step). Why now: the wiki already has the plane machinery (separate SQLite planes, overlay namespaces with prefix routing, `content_hash` read-repair, cross-kind `neighbors`), `sqlglot` is a core dependency, and `TableMetadata` is already a dialect-neutral record — the missing piece is only the persistence and the ids.

## Constraints & Requirements

- **Ids are `origin`-first, dialect-ordered.** Owner's requirement: a table is addressed as *origin:object* — `bigquery:epson.sales`. The origin is the first-class discriminator, objects are grouped under it, and `origin` defaults to the dialect when a project has one source per dialect (see Option B for the exact grammar and why the entity kind must stay in front of it).
- **Never store credentials in the plane.** The `source:` page carries an alias, the dialect, `allowed_schemas` and a `dsn_env` *name*; the DSN itself comes from `navconfig` at sync time. Same rule as `arango_credentials_env` in `WikiProjectConfig`. Security invariant: nothing in a page can reach the LLM that would let it connect.
- **`sample_data` off by default.** Row counts, comments and statistics are fine; sample rows are PII-adjacent and only enter the plane per-table on an explicit allowlist.
- **One record, many producers.** Live introspection (`SQLToolkit` dialect hooks), offline DDL (`.sql` migrations via `sqlglot`) and later model reflection must all produce the same `TableMetadata`; the page renderer never knows where the metadata came from — it only records `source` and `introspected_at`.
- **Freshness is per table, never per schema.** A lookup returns the stored page; re-introspection happens for the *hit* tables only, driven by a hash + age policy or by a database error that proves staleness (`retries.py` already classifies `"column does not exist"` / `"relation does not exist"`). No tool ever runs a full `information_schema` scan on the request path.
- **Annotations survive sync.** Human/agent notes about a table must not be overwritten by the next `schema sync`. Ingested pages are replaced; authored pages (`origin="authored"` / `"memory"`) are linked, never rewritten.
- **Plane is `BaseWikiStore`-agnostic.** SQLite under `.parrot/` for the dev loop; the same class over `postgres` / `arangodb` backends for a production `DatabaseAgent` fleet. No new heavy dependency: `SQLiteWikiStore`, `FederatedWikiStore`, `NamespaceHandle`, `sqlglot`, `asyncdb` are all already there.
- **Same shared-root policy as the ledger.** In a git checkout the plane lives at the main worktree's `.parrot/schema/` (`find_shared_root`); linked worktrees read it, never write it. A schema is environment-dependent, not branch-dependent, so this costs less than it did for `sym:`.
- **Language split:** identifiers, page ids, CLI verbs and docs in English.
- **Validation-first:** spikes (§Spike Gate) before `/sdd-spec`.

---

## Options Explored

### Option A: Table pages inside the main `wiki.db` (category `table`, like the decisions plane)

Add `table` / `schema` / `source` categories to the existing project wiki, exactly as FEAT-578 stores ADRs as pages with `category=ADR_CATEGORY` in the same store. `wikitoolkit schema sync` writes them through `replace_source_slice(source_id="schema:<origin>")`; `neighbors()` crosses `table:` → `sym:` natively because everything is one graph.

✅ **Pros:**
- Zero new files, zero federation work; `wiki_query` / `wiki_related` / `wiki_page` see tables on day one.
- The decisions plane already proved the "extra category in the same store" path, including `list_pages(category=…)`.

❌ **Cons:**
- Lifecycle mismatch: `wiki.db` is a **base-branch snapshot of the repo** (rebuilt by `build`, upserted by post-commit hooks, held under `wiki.lock` for minutes). A schema changes when a *database* migrates, not when code commits; a `schema sync` from a cron or a running agent contends with `build` for the same lock and the same `_migrate()` hot spot the ledger design already documented.
- Cannot be mounted per environment: dev and prod schemas of the same origin would need two project wikis.
- No way to give a production `DatabaseAgent` (no repo, no `.parrot/`) the plane without shipping the whole code wiki with it.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiosqlite`, `sqlglot` | store, DDL parse | already dependencies |

🔗 **Existing Code to Reuse:**
- `knowledge/wiki/decisions/repository.py::DecisionRepository` — same-store category pattern.
- `knowledge/wiki/store.py::replace_source_slice` — slice replace per origin.

---

### Option B: Separate **schema plane** (`.parrot/schema/schema.db`) mounted as an overlay namespace — *recommended*

Mirror FEAT-566: a `SchemaStore(SQLiteWikiStore)` in its own directory, opened by a `SchemaPlaneService.from_root(root)` and mounted in `mcp_server.py` as a read-only `NamespaceHandle(name="schema", config=WikiNamespaceConfig(store=…, overlay_prefixes=["source", "schema", "table"]))`, next to the ledger handle. Federation already routes bare ids by prefix and hydrates cross-kind neighbors (overlay → code and back), so `table:` ↔ `sym:` ↔ `file:` edges work with no new read path.

**Id grammar.** The owner's *origin:object* is kept as the ordering principle, with the entity kind in front of it so that the federation's prefix routing (`overlay_prefixes`) and every existing tool that derives *kind* from the id prefix (`issue:`, `sym:`, `file:`) keep working:

```
source:<origin>                          source:bigquery       source:navigator
schema:<origin>/<schema>                 schema:bigquery/epson  schema:navigator/public
table:<origin>/<schema>.<table>          table:bigquery/epson.sales
                                         table:navigator/public.stores
```

`<origin>` is a declared source alias; it **defaults to the dialect** (`bigquery`, `postgres`, `mssql`, … — the keys of `_SQLGLOT_DIALECT_MAP`), so a project with one BigQuery and one Postgres source gets exactly `bigquery:epson.sales`-shaped ids, and a project with two Postgres databases declares `navigator` / `troc` instead of colliding under `postgres`. `<schema>` is whatever the dialect calls it (Postgres schema, BigQuery dataset, MSSQL `db.schema` collapsed with a dot). Columns are **not** pages: they live in a `columns` side table (same trade-off FEAT-498 made for `symbols`, and for the same reason — page count and FTS noise) and are rendered into the table page.

**Page shape** (OKF principle: JSON authoritative, text a deterministic projection):

- `body` = frontmatter (origin, dialect, schema, table, table_type, completeness, source, introspected_at, content_hash, row_count) + `## DDL` (canonical `CREATE TABLE` rendered through `sqlglot.exp.Create(...).sql(dialect=…)` from the `TableMetadata`, so the DDL is per-dialect for free and byte-stable) + `## Columns` (name, type, nullable, default, comment) + `## Relations` (FKs in/out, view dependencies).
- `content_hash` = sha1 of the normalised `TableMetadata` JSON **minus** volatile fields (`row_count`, `last_accessed`, `access_frequency`, `avg_query_time`, `loaded_at`).
- Edges: `contains` (`source`→`schema`→`table`), `references` (FK, `provenance="extracted"`; the column pair lives in the `columns` side table as `fk_target`, not on the edge — see Open Questions), `depends_on` (view → table), `defined_in` (`table` → `file:<migration>.sql`), `maps_to` (`sym:<Model>` → `table`, v2).
- Annotations: `wiki_remember(fact, link_page_id="table:bigquery/epson.sales", rel="about")` — the existing tool, the existing `mem-<sha1>` pages, `origin="memory"`. `schema sync` only replaces the ingested slice (`source_id="schema:<origin>"`), so notes persist; `wiki_schema_lookup` inlines `neighbors(rel="about")`.

**Producers** (all emit `TableMetadata`):
1. `schema sync <origin>` — instantiates the matching `SQLToolkit` subclass (`PostgresToolkit` for `pg_catalog`, `BigQueryToolkit`, generic `SQLToolkit` for `information_schema` dialects) from `source:` config + `dsn_env`, iterates `allowed_schemas`/`tables`, calls `describe_table` (FULL) and writes pages; `--changed` compares `content_hash` and rewrites only drifted tables.
2. `schema ingest-ddl <paths> --origin <o> --dialect <d>` — `sqlglot.parse(..., read=dialect)` over `.sql` files (32 in the monorepo today, e.g. `parrot-formdesigner/migrations/*.sql`, `storage/security_reports/schema.sql`), folding `exp.Create` / `exp.ColumnDef` / `exp.PrimaryKey` / `exp.ForeignKey` / `exp.AlterTable` in file order into `TableMetadata(source="ddl")`. Adds `defined_in` edges to the `file:` pages the structural plane already has (`.sql` is in `file_suffixes`). Works with **no database connection** — this is the SDD/dev-loop path.
3. `schema diff <origin>` — live vs. DDL for the same origin; drift becomes a report and, optionally, `wikitoolkit ledger open --kind tech_debt --about table:…`.

**Freshness.** Read path never introspects. `wiki_schema_lookup` returns the page plus `age`; a `stale_after` policy per completeness (reuse `ttl_by_completeness` semantics, but in days not seconds) marks pages `stale: true` in the response so the agent knows. Repair triggers: (a) `schema sync --changed` from cron / post-merge hook; (b) **error-driven read-repair** — when `SQLToolkit` classifies an execution error as `"column does not exist"` / `"relation does not exist"` (`retries.py`), it re-runs `describe_table` for the referenced tables and write-through upserts the plane, same shape as `StructuralService._ensure_fresh` but keyed on a proven-stale signal instead of a file hash.

**Runtime integration.** `CachePartition` gains an optional **plane tier** between Redis and the vector store: `LRU → schema cache → Redis → plane → vector store → information_schema`, and `store_table_metadata` writes through to the plane when `plane_write=True`. `_warm_table_cache` then warms from the plane, not from the database; `validate_query`'s `"not found in cache"` becomes "not found in plane" (a much stronger statement). `generate_query`'s schema context is built from `wiki_schema_neighbors` (join paths) instead of a flat list.

**Tools** (one action per tool, per the design invariant): MCP `wiki_schema_lookup`, `wiki_schema_search` (FTS over table names, column names, comments), `wiki_schema_neighbors` (FK graph, `depth`, returns join paths), `wiki_schema_sources`; `SchemaPlaneToolkit(AbstractToolkit, tool_prefix="schema")` wrapping the same four for any ai-parrot agent; CLI `wikitoolkit schema {sources,add-source,sync,ingest-ddl,diff,lookup}`. Writes stay CLI-only in v1 (sync needs credentials; the MCP has none).

✅ **Pros:**
- Same pattern as the ledger, already shipped: separate low-contention SQLite file, overlay namespace, cross-kind neighbors — the federation code paths are exercised, not new.
- Lifecycle matches reality: the plane changes when a database changes; `build` never touches it and it never touches `wiki.lock`.
- Offline path for coders (DDL ingest) and online path for agents (live sync) produce the same pages, so a `sdd-coder` and a `DatabaseAgent` reason about the identical `table:bigquery/epson.sales`.
- Backend swap is free: `SchemaStore` is a `BaseWikiStore`; a production fleet points it at `postgres` / `arangodb` and shares one plane across agents and hosts.
- Ids are exactly the owner's *origin:object*, dialect-ordered, without breaking prefix routing.

❌ **Cons:**
- One more directory and DB under `.parrot/`; one more CLI group.
- Two producers for one page means a merge policy when both exist for the same origin (live wins for facts, DDL keeps `defined_in`; see Open Questions).
- `sqlglot` DDL coverage is uneven per dialect (T-SQL and Oracle DDL in particular) — the offline path is only as good as the parser; spike required.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiosqlite` | `schema.db` | already the store driver |
| `sqlglot>=20.0` | DDL parse + canonical DDL render | already a core dependency (FEAT-062) |
| `asyncdb` (`pg`, `bigquery`, …) | live introspection | via the existing `SQLToolkit` subclasses |
| `click` | `wikitoolkit schema` group | already the CLI framework |

🔗 **Existing Code to Reuse:**
- `knowledge/wiki/ledger/store.py::LedgerStore`, `ledger/service.py::LedgerService.from_root` — the plane-in-its-own-dir template; `mcp_server.py` ledger mount block (`NamespaceHandle` + `overlay_prefixes`) — copy for `schema`.
- `knowledge/wiki/federation.py::FederatedWikiStore.neighbors` — overlay ↔ code hydration already handles cross-kind edges.
- `knowledge/wiki/store.py::SQLiteWikiStore` — `replace_source_slice`, `page_hashes`, `neighbors`, `search_fts`, `compare_and_swap_page`; `upsert_symbols` / `find_symbols` as the model for a `columns` side table.
- `knowledge/wiki/symbols.py::sym_concept_id / parse_sym_id / symbol_to_page_fields` — pattern for `table_concept_id / parse_table_id / table_to_page_fields`.
- `knowledge/wiki/structural/service.py::StructuralService._ensure_fresh` — read-repair shape.
- `bots/database/models.py::TableMetadata, SchemaMetadata, Completeness, MetadataSource` — the record (extend `MetadataSource` with `"ddl"`).
- `bots/database/toolkits/sql.py::SQLToolkit.describe_table / search_schema / _get_columns_query / _get_primary_keys_query / _get_unique_constraints_query`, `postgres.py::PostgresToolkit` (`pg_catalog`), `bigquery.py::BigQueryToolkit._get_information_schema_query` — the live producers; `_SQLGLOT_DIALECT_MAP` — the origin default list.
- `bots/database/cache.py::CachePartition.get / store_table_metadata / _warm_table_cache` — add the plane tier.
- `bots/database/retries.py` — stale-signal classification for error-driven repair.
- `bots/database/toolkits/_internal.py::generate_create_table_statement / simplify_column_type` — superseded by the sqlglot renderer, keep for compatibility.
- `knowledge/wiki/tools.py::WikiRememberTool` (`link_page_id`, `rel`) — annotations as-is.
- `flows/dev_loop/wiki_search.py::DevLoopWikiSearch.build_research_context` — include `table:` hits when the task scope names tables or models.

---

### Option C: Durable `CachePartition` only (persist `TableMetadata` without TTL; no wiki)

Keep everything inside `bots/database`: add a persistent tier to `CachePartition` (Postgres table `schema_metadata(origin, schema, table, json, content_hash, introspected_at)` via `asyncdb`, or Redis without expiry) and stop evicting FULL entries. `_warm_table_cache` reads that tier.

✅ **Pros:**
- Smallest change; fixes the cold-start and BigQuery-cost problem for `DatabaseAgent` immediately.
- No wiki, no federation, no CLI.

❌ **Cons:**
- Solves only problem 1. Coders still have nothing (no `.parrot/`, no MCP exposure, no offline DDL path); no graph (join paths, `maps_to`, `defined_in`); no annotations; no `wiki_related` from a symbol to its table.
- Creates a second, private "knowledge store" next to the wiki — the opposite of the plane direction the project has taken for symbols, ledger and decisions.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb`/`asyncpg` or Redis | durable tier | already in the stack |

🔗 **Existing Code to Reuse:**
- `bots/database/cache.py` — the whole change lives here.

*(Worth keeping as the **runtime face** of Option B: the plane tier in `CachePartition` is exactly this, with the plane as the store.)*

---

### Option D: Knowledge-graph namespace in GraphIndex / ArangoDB (`schema:<origin>` next to `legal:core`)

Model sources, schemas, tables and columns as GraphIndex nodes in ArangoDB with typed edges and AQL traversals (join paths as graph queries), bitemporal history of schema changes (`valid_from`/`valid_to` per column), exposed through GraphIndex retrieval to every agent.

✅ **Pros:**
- Real graph traversals and schema history for free; fits a production multi-agent, multi-host deployment; aligns with the GraphIndex Postgres/Arango work.
- Columns can be first-class nodes without SQLite FTS cost concerns.

❌ **Cons:**
- Requires a running service for the dev loop — the `wikitoolkit` value is that `.parrot/` works offline in a worktree.
- Duplicates the page/edge/FTS/MCP surface the wiki already federates; the wiki's `arangodb` backend already exists as `arango_store.py`, so this is reachable from Option B as a backend, not as a separate system.
- Over-scoped for v1; schema history is a real want (Open Questions) but not the blocking problem.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-arango` | graph store | `arango_store.py` exists |

🔗 **Existing Code to Reuse:**
- `knowledge/wiki/arango_store.py` — as Option B's production backend later.

---

## Recommendation

**Option B.** It is the only option that serves both consumers — the running `DatabaseAgent` and the coding agent in a worktree — with one id space and one page format, and it does so by copying a pattern that already shipped (ledger: own SQLite file, overlay namespace, prefix routing, cross-kind neighbors) rather than inventing one. The owner's *origin:object* addressing is preserved verbatim in the second segment (`table:bigquery/epson.sales`); putting the entity kind first is what keeps `overlay_prefixes`, `wiki_related` and every prefix-derived *kind* in the codebase working unchanged.

What we trade: a second plane directory, a merge rule between live and DDL producers, and a dependency on `sqlglot`'s DDL coverage for the offline path (Postgres and BigQuery are solid; T-SQL/Oracle are the spike). Option C is absorbed as the `CachePartition` plane tier; Option D remains a backend swap because the plane is a `BaseWikiStore`. Option A is rejected on lifecycle grounds — a schema is not a property of a git branch.

---

## Feature Description

### User-Facing Behavior

- **Declare a source once**: `wikitoolkit schema add-source bigquery --dialect bigquery --dsn-env EPSON_BQ_DSN --schemas epson` writes `source:bigquery` (alias, dialect, schemas, env *name*) into `.parrot/wiki.json` under `schema.sources`. Alias defaults to the dialect; a second source of the same dialect must name itself.
- **Sync**: `wikitoolkit schema sync bigquery [--tables epson.sales,epson.products] [--changed]` introspects through the dialect's toolkit and writes `table:bigquery/epson.*` pages; prints `created / updated / unchanged / stale-removed`. Never runs from a linked worktree (writes to the shared root only).
- **Offline ingest**: `wikitoolkit schema ingest-ddl packages/parrot-formdesigner/migrations --origin formdesigner --dialect postgres` builds the same pages from migrations, with `defined_in` edges to `file:` pages. This is what the post-merge hook runs in the main worktree when `.sql` files changed.
- **Lookup from Claude Code / any agent**: `wiki_schema_lookup("bigquery:epson.sales")` (bare *origin:object* accepted and normalised to `table:bigquery/epson.sales`) returns frontmatter, DDL, columns, relations, annotations and `age` / `stale`. `wiki_schema_neighbors("bigquery:epson.sales", depth=2)` returns FK join paths. `wiki_schema_search("store id")` does FTS over names and comments. `wiki_query` / `wiki_related` also see the pages through the `schema` namespace.
- **Annotate**: `wiki_remember("store_id is the T-ROC store id, not Epson's", link_page_id="table:bigquery/epson.sales", rel="about")` — no new tool; the note appears inside the next `wiki_schema_lookup`.
- **Drift**: `wikitoolkit schema diff bigquery` prints DDL-vs-live differences per table; `--ledger` files them as `tech_debt` issues with `about` edges.
- **`DatabaseAgent`** gains `schema_plane=<store or dir>`; when set, toolkits warm from the plane, `describe_table` misses fall through to the plane before the database, and successful introspections write through. Nothing changes for agents that do not set it.

### Internal Behavior

1. `knowledge/wiki/schema/` (new): `models.py` (`SchemaSourceConfig`, `TableRecord` = thin Pydantic wrapper over `TableMetadata` + `origin`/`dialect`, `ColumnRecord`), `ids.py` (`table_concept_id(origin, schema, table)`, `parse_table_id`, `normalize_ref("bigquery:epson.sales")`), `render.py` (`render_ddl(record, dialect)` via `sqlglot.exp.Create`, `render_page(record) -> WikiPageRecord`, `content_hash(record)`), `store.py` (`SchemaStore(SQLiteWikiStore)` + `columns` table, `upsert_columns`, `find_columns`), `producers/live.py` (toolkit-backed introspection), `producers/ddl.py` (sqlglot fold), `service.py` (`SchemaPlaneService.from_root`, `sync`, `ingest_ddl`, `diff`, `lookup`, `neighbors`, `search`), `tools.py` + `toolkit.py` (four read tools; `SchemaPlaneToolkit`).
2. `WikiProjectConfig.schema: SchemaPlaneConfig` (`sources: dict[str, SchemaSourceConfig]`, `include_samples: bool = False`, `stale_after_days: dict[Completeness, int]`, `enabled: bool`), `schema_path(root) -> <shared>/.parrot/schema/`.
3. `mcp_server.py`: mount `schema` as a read-only overlay handle next to `ledger` when `SchemaPlaneService.from_root(root)` finds a built plane; append `create_schema_tools(read_store, root, config)`.
4. `cli.py`: `wikitoolkit schema` group; `sync`/`ingest-ddl`/`diff` refuse to run when `is_linked_worktree(root)`.
5. `bots/database/cache.py`: `CachePartition(plane: SchemaPlaneReader | None, plane_write: bool)`; tier inserted after Redis; `store_table_metadata` write-through; `_warm_table_cache` prefers the plane.
6. `bots/database/toolkits/sql.py`: on a stale-classified execution error, `describe_table` the referenced tables (already extracted by `validate_query`) and write through; `generate_query` context assembled from plane neighbors when available.
7. Merge rule (live + DDL for one origin): live is authoritative for facts (columns, types, constraints); DDL only creates pages for tables with no live counterpart (`source="ddl"`) and always contributes `defined_in` edges; divergence is recorded by `diff`, never silently resolved.
8. Hooks: the existing `post-merge` block in the main worktree additionally runs `schema ingest-ddl --changed` for modified `.sql` files (same `is_linked_worktree` guard as the structural upsert).

### Edge Cases & Error Handling

- **Unknown alias in a lookup** (`wiki_schema_lookup("epson.sales")` with no origin) → if exactly one source declares that schema, resolve and say so in the response; otherwise return the candidate ids, never guess.
- **Alias collision** (`add-source postgres` twice) → refuse with the existing alias listed; suggest naming.
- **DDL parse failure on a file** → the file is skipped and reported (`parse_errors[]`); the run never fails as a whole. Unsupported statements are ignored, not fatal.
- **Live sync partial failure** (one table errors) → other tables are written; the failing table keeps its previous page with `stale: true` and the error in the report.
- **`ALTER TABLE` sequences in migrations** → folded in file-name order per origin; `ingest-ddl` documents that ordering is lexical and offers `--order manifest.json` for custom order.
- **Views / materialised views** → `table_type` preserved; `depends_on` edges extracted from the view definition with `sqlglot` where the dialect exposes it (`pg_get_viewdef`, BigQuery `INFORMATION_SCHEMA.VIEWS`); best-effort, `provenance="extracted"`.
- **Cross-origin FKs** (rare, e.g. federated Postgres) → edge to a dangling `table:` id; `neighbors()` already returns dangling targets; `schema diff` reports them.
- **Plane missing at runtime** → `CachePartition` behaves exactly as today; `DatabaseAgent` logs once.
- **Schema renamed / table dropped** → `sync` removes pages no longer present for that origin (`replace_source_slice` semantics) and logs them; annotations (`mem-*` pages) become dangling `about` edges, surfaced by `broken_edges()`, not deleted.

---

## Capabilities

### New Capabilities
- `wiki-schema-plane`: `SchemaStore`, ids, page renderer, `columns` side table, `SchemaPlaneService`.
- `wiki-schema-producers`: live (toolkit-backed) and DDL (`sqlglot`) producers emitting `TableMetadata`; merge rule; `diff`.
- `wiki-schema-tools`: four MCP read tools, `SchemaPlaneToolkit`, `wikitoolkit schema` CLI group, overlay namespace mount.
- `database-plane-tier`: `CachePartition` plane tier + write-through; error-driven read-repair in `SQLToolkit`.

### Modified Capabilities
- `wiki-project-config`: `schema` section, `schema_path`.
- `wiki-mcp-server`: second overlay handle; tool count grows by four when a plane is built.
- `wiki-claude-code-hooks`: `post-merge` runs `schema ingest-ddl --changed`.
- `database-agent`: optional `schema_plane` argument; `validate_query` wording; `generate_query` context source.
- `dev-loop-research-context`: `table:` hits included when relevant.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `knowledge/wiki/schema/` (new) | new | models, ids, render, store, producers, service, tools, toolkit |
| `knowledge/wiki/project.py` | extends | `SchemaPlaneConfig`, `schema_path`, `WikiProjectConfig.schema` |
| `knowledge/wiki/mcp_server.py` | extends | `schema` overlay mount + tools (copy of the ledger block) |
| `knowledge/wiki/cli.py` | extends | `wikitoolkit schema` group |
| `knowledge/wiki/claude_code/{assets,installer}.py` | modifies | post-merge DDL ingest; permissions `mcp__wikitoolkit__wiki_schema_*` |
| `bots/database/models.py` | extends | `MetadataSource` += `"ddl"`; optional `origin` on `TableMetadata` |
| `bots/database/cache.py` | modifies | plane tier, write-through — behaviour-preserving when unset |
| `bots/database/toolkits/sql.py` | modifies | error-driven repair; plane-aware `validate_query` / `generate_query` |
| `bots/database/agent.py` | extends | `schema_plane` wiring into partitions |
| `flows/dev_loop/wiki_search.py` | extends | include `table:` pages |
| `tools/dataset_manager/sources/sql.py` | optional | `prefetch_schema` may read the plane (follow-up) |
| `.parrot/wiki.json` | extends | `schema.sources`, `schema.include_samples`, `schema.stale_after_days` |

No breaking API changes. Everything is opt-in behind a declared source or a `schema_plane` argument.

---

## Code Context

### User-Provided Code
_None — requirement given in prose: a wikitoolkit plane holding SQL metadata (CREATE TABLEs, schemas) so agents stop hitting `information_schema` per call; ids as origin:object, e.g. `bigquery:epson.sales`, ordered by dialect._

### Verified Codebase References
_Paths relative to `packages/ai-parrot/src/parrot/` unless noted; verified against `main` on 2026-09-24. Grep anchors, not line numbers._

#### Classes & Signatures
```python
# knowledge/wiki/project.py
class WikiNamespaceConfig(BaseModel):      # fields: path | store | vault (exactly one), backend, database, credentials_env, description, weight, overlay_prefixes
class WikiProjectConfig(BaseModel):        # wiki_name, storage_dir, backend: Literal["sqlite","memory","arangodb"], namespaces, symbol_depth, structural_backend, decisions, sqlite_busy_timeout, sqlite_performance_pragmas
    def ledger_path(self, root: Path) -> Path      # precedent for schema_path
def find_shared_root(...)                  # used by mcp_server before mounting the ledger

# knowledge/wiki/mcp_server.py — ledger mount (copy for schema):
ledger_config = WikiNamespaceConfig(store=str(ledger_dir), description=..., weight=0.5, overlay_prefixes=["issue","task","spec","insight"])
handles.append(NamespaceHandle(name="ledger", store=ledger_service.store, config=ledger_config, storage_dir=ledger_dir, read_only=True))
read_store = FederatedWikiStore(store, config.wiki_name, handles, skipped)
structural_tools = create_structural_tools(read_store, root, config); decision_tools = create_decision_tools(read_store, root, config)

# knowledge/wiki/federation.py
class FederatedWikiStore(BaseWikiStore):   # neighbors(): "Overlay outgoing-to-code: when the seed is in an overlay namespace and a neighbor's kind is NOT in that overlay's prefixes, return the neighbor unqualified and hydrated" — cross-kind edges already resolved
class NamespaceHandle:                     # name, store, config, storage_dir, read_only; .kind ∈ path/store/vault/database

# knowledge/wiki/store.py
class WikiPageRecord(BaseModel):           # concept_id, node_id, title, category (open str), summary, body, source_id, token_count, origin ("ingest"|"authored"|"memory"), asserted_by, updated_at, content_hash
class BaseWikiStore:                       # upsert_pages, add_edges, replace_source_slice(source_id, pages, edges), get_page, list_pages, search_fts, neighbors, compare_and_swap_page,
                                           # upsert_symbols / symbols_for / find_symbols / search_symbols_fts / page_hashes  ← side-table precedent for `columns`
def create_wiki_store(storage_dir, wiki_name, backend, **kwargs)   # "sqlite" | "memory" | "arangodb" | "postgres" | registered
class SQLiteWikiStore(BaseWikiStore)

# knowledge/wiki/ledger/store.py
class LedgerStore(SQLiteWikiStore):        # "SQLiteWikiStore specialisation for ledger.db" — template for SchemaStore
# knowledge/wiki/ledger/service.py
LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=policy)

# knowledge/wiki/symbols.py
class SymbolRecord(BaseModel)              # rel_path, language, kind, name, qualname, parent, signature, doc, exported, ..., content_hash, depth
def sym_concept_id(rel_path, qualname, ordinal=1) -> str; def parse_sym_id(concept_id); def symbol_to_page_fields(record, *, source_excerpt="")

# knowledge/wiki/structural/service.py
async def _ensure_fresh(self, rel_paths: list[str]) -> list[str]   # page_hashes() vs on-disk sha1 → rescan hits only (read-repair)

# knowledge/wiki/tools.py
class WikiRememberTool: name = "wiki_remember"   # input: fact, category="note", title=None, link_page_id=None, rel="references"
# structural/tools.py: wiki_symbol_lookup, wiki_code_outline, wiki_blast_radius; decisions/tools.py: wiki_decisions_for_symbol, wiki_decision_why, wiki_decision_generate

# bots/database/models.py
class Completeness(IntEnum): NAME_ONLY=1; WITH_COLUMNS=2; FULL=3
MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "unknown"]
@dataclass class TableMetadata: schema, tablename, table_type, full_name, comment, columns, primary_keys, foreign_keys, indexes, row_count, sample_data, unique_constraints, last_accessed, access_frequency, avg_query_time, completeness, loaded_at, source
@dataclass class SchemaMetadata: database_name, schema, table_count, view_count, total_rows, last_analyzed, database_type, tables, views, functions

# bots/database/toolkits/sql.py
_SQLGLOT_DIALECT_MAP = {"postgresql","postgres","bigquery","mysql","mariadb","sqlite","mssql","sqlserver","oracle","clickhouse","duckdb","redshift","snowflake"} → sqlglot names
class SQLToolkit(DatabaseToolkit): _metadata_source = "information_schema"
    async def search_schema(...); async def describe_table(self, schema, table) -> Optional[TableMetadata]   # cache first, FULL introspection on miss
    async def validate_query(self, sql) -> Dict   # "Table '<s>.<t>' not found in cache." when cache_partition misses
    def _get_information_schema_query(...); _get_columns_query(schema, table); _get_primary_keys_query; _get_unique_constraints_query; _get_sample_data_query
    async def _warm_table_cache(self)          # pre-populates cache_partition from self.tables via the DB
# bots/database/toolkits/postgres.py: class PostgresToolkit(SQLToolkit): _metadata_source = "pg_catalog"
# bots/database/toolkits/bigquery.py: class BigQueryToolkit(SQLToolkit)  # overrides _get_information_schema_query
# bots/database/toolkits/base.py: class DatabaseToolkitConfig(dsn, allowed_schemas=["public"], primary_schema, tables, read_only, database_type="postgresql", use_pool, pool_params); _DRIVER_MAP → asyncdb driver ("pg", "bigquery", "influx", ...)

# bots/database/cache.py
class CachePartitionConfig(BaseModel): namespace, lru_maxsize=500, lru_ttl=1800, redis_ttl=3600, ttl_by_completeness
class CachePartition:  # get(): "Resolution order: LRU → schema cache → Redis → vector store"; store_table_metadata(); list(); search(); _warm via toolkit
# bots/database/agent.py: tk_id = f"{tk.database_type}_{tk.primary_schema}"; CacheManager.create_partition(CachePartitionConfig(namespace=tk_id, ...)); query_router.register_database(tk.database_type, tk_id)
# bots/database/retries.py: stale signals "column does not exist", "relation does not exist"; _get_sample_data_for_error(...)

# tools/dataset_manager/sources/sql.py
class SQLQuerySource(DataSource): async def prefetch_schema(self) -> Dict[str, str]   # "Return empty dict — schema only available after first fetch."
```

#### Verified Imports
```python
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, BaseWikiStore, create_wiki_store
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle
from parrot.knowledge.wiki.project import WikiNamespaceConfig, WikiProjectConfig, find_shared_root
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.symbols import SymbolRecord, sym_concept_id, parse_sym_id
from parrot.bots.database.models import TableMetadata, SchemaMetadata, Completeness
from parrot.bots.database.cache import CachePartition, CachePartitionConfig
from parrot.bots.database.toolkits.sql import SQLToolkit
import sqlglot  # core dependency: packages/ai-parrot/pyproject.toml "sqlglot>=20.0" (FEAT-062)
```

#### Key Attributes & Constants
- `.sql` is in `knowledge/wiki/file_suffixes.py` → `repo_scan` already emits `file:` pages for migrations (content head only; there is no SQL language scanner in `languages/`).
- 32 `.sql` files in the monorepo today, e.g. `packages/parrot-formdesigner/migrations/00N_*.sql`, `parrot/storage/security_reports/schema.sql`, `parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql` — the DDL-ingest spike corpus.
- `WikiNamespaceConfig` validator requires exactly one of `path` / `store` / `database` / `vault`; the ledger sets `store=` only to satisfy it and wraps an already-open store in the `NamespaceHandle` — do the same.
- `project.py` already has `resolve_git_common_dir`, `is_linked_worktree`, `find_shared_root` (FEAT-566); `installer._git_hook_path(root, hook_name)` already installs `post-commit` **and** `post-merge` (FEAT-566 Module 10) — the schema hook is one more line in the existing block, not a new hook.
- `WikiProjectConfig.backend` is `Literal["sqlite","memory","arangodb"]` while `create_wiki_store` also accepts `"postgres"` — a production plane on Postgres needs the Literal widened or a plane-specific `backend` field.
- Decisions plane (FEAT-578) stores ADRs **in the main `wiki.db`** by category; ledger (FEAT-566) uses **its own `ledger.db`** — the two precedents behind Options A and B.
- `wikitoolkit` CLI already has groups `ns`, `ledger`, `symbols`, `sync`; `schema` is free.

### Does NOT Exist (Anti-Hallucination)
- ~~any `table:` / `schema:` / `source:` page kind, or `knowledge/wiki/schema/`~~ — nothing under `wiki/` knows about databases.
- ~~`SchemaStore`, `SchemaPlaneService`, `wiki_schema_*` tools, `wikitoolkit schema` group~~ — all new.
- ~~a persistent tier in `CachePartition`~~ — tiers are LRU, schema cache (in-memory), Redis (TTL), vector store; nothing survives a Redis expiry.
- ~~any `sqlglot` DDL parsing~~ — `sqlglot` is used only for query validation/dialect transpile (`SQLToolkit`, `security/query_validator.py`, `tools/databasequery/base.py`, `dataset_manager/sources/{authorizing,resolver}.py`); no `exp.Create` handling anywhere.
- ~~`MetadataSource` value `"ddl"` or an `origin` field on `TableMetadata`~~ — sources today: `frontend | information_schema | pg_catalog | unknown`.
- ~~asyncdb-level introspection in the bots~~ — introspection is hand-written SQL per dialect in `SQLToolkit` / `PostgresToolkit` / `BigQueryToolkit`; no `column_info`/`table_info` calls.
- ~~a "Postgres" `WikiProjectConfig.backend`~~ — the Literal stops at `arangodb` even though `postgres_store.py` exists.
- ~~a `columns` side table or FTS over columns~~ — only `symbols` exists.
- ~~hooks running anything schema-related~~ — `post-commit` / `post-merge` run `wikitoolkit upsert --changed` only (no-op inside linked worktrees).
- ~~`DatasetManager` schema knowledge before first fetch~~ — `SQLQuerySource.prefetch_schema` returns `{}`.
- ~~edge payloads~~ — edges are `(src, dst, rel[, provenance])`; there is no column-pair field for FK edges (see Open Questions).

---

## Spike Gate (before `/sdd-spec`)

1. **DDL fidelity.** `sqlglot.parse(read=…)` over the 32 in-repo `.sql` files plus one representative BigQuery DDL and one T-SQL DDL: report tables/columns/PK/FK recovered vs. hand count; list unsupported constructs. Pass = Postgres ≥ 95 % of columns and all FKs; BigQuery ≥ 90 %; T-SQL is informational.
2. **Overlay round-trip.** Mount a throwaway `schema.db` as an overlay with `overlay_prefixes=["table"]`, add `table:x/a.b --references--> table:x/a.c` and `sym:m.py#Model --maps_to--> table:x/a.b`; assert `wiki_related("sym:m.py#Model")` and `wiki_related("table:x/a.b")` both hydrate across the boundary. (Same mechanism FEAT-566 relies on; confirm it holds for a second overlay.)
3. **BigQuery cost baseline.** Time and bytes billed for `BigQueryToolkit.describe_table` (FULL) over the Epson dataset once, vs. reading the same tables from the plane — the number that justifies the feature for that client.
4. **Plane tier regression.** Insert the plane tier into `CachePartition` behind a flag; the existing `bots/database` test suite must pass with the flag off and on (plane = in-memory `SQLiteWikiStore`).

---

## Parallelism Assessment

- **Internal parallelism**: yes, after a small foundation. Lane 1 (`schema/models.py`, `ids.py`, `render.py`, `store.py`, `project.py` config) is the contract everything imports. Lane 2 (`producers/live.py` + CLI `sync`/`diff`) and Lane 3 (`producers/ddl.py` + CLI `ingest-ddl` + post-merge hook) are independent once `TableRecord` is frozen. Lane 4 (tools, toolkit, MCP mount) and Lane 5 (`CachePartition` tier + `SQLToolkit` repair) can proceed against Lane 1's interface.
- **Cross-feature independence**: touches `mcp_server.py` and `claude_code/{assets,installer}.py` (shared with FEAT-566/498 lineage — land the hook change once), and `bots/database/{cache,sql}.py` (shared with the small tool-calling-model work only at the toolkit surface, not internally).
- **Recommended isolation**: `mixed` — one worktree for Lane 1, then per-lane worktrees.
- **Rationale**: the foundation is a handful of models and one store subclass; the rest is additive modules plus opt-in flags.

---

## Open Questions

Resolved 2026-09-24 against the codebase research in `sdd/state/FEAT-600/` (proposal
`sdd/proposals/sql-schema-plane.proposal.md`, FEAT-600). Finding ids (`F0xx`) refer to
`sdd/state/FEAT-600/findings/`.

- [x] **Id grammar, final call** — *Resolved*: **kind-first** `table:<origin>/<schema>.<table>`
  (likewise `schema:<origin>/<schema>`, `source:<origin>`). `FederatedWikiStore._route_bare_overlay_id`
  routes a bare id by its *kind prefix* to the overlay whose `overlay_prefixes` contain it (F002), so
  the kind must be the first segment; the bare `bigquery:epson.sales` form would make the kind of an
  id depend on a config lookup, and per-origin namespaces would mean N SQLite files. The owner's
  *origin:object* form is preserved verbatim as the second segment and is accepted **on input** by
  `normalize_ref("bigquery:epson.sales") → "table:bigquery/epson.sales"` in every lookup tool and
  CLI verb. — *Owner: Jesus*
- [x] **Origin = alias or `tk_id`?** — *Resolved*: **alias**, declared explicitly. `DatabaseToolkitConfig`
  gains `origin: str | None` defaulting to `database_type`; `DatabaseAgent` passes it into the
  partition (`CachePartition(plane=…, origin=…)`). `tk_id = f"{database_type}_{primary_schema}"`
  (agent.py L206, F009) stays untouched — it is also the `query_router` registration key. — *Owner: Jesus*
- [x] **Columns as pages?** — *Resolved*: **side table** in v1 (`columns`, mirroring `symbols` — F003),
  rendered into the table page and searchable via `wiki_schema_search`. `col:` pages can be added
  later without changing table ids. — *Owner: Jesus*
- [x] **FK edge payload** — *Resolved*: **no edge attribute in v1**. `edges` is `(src, dst, rel,
  provenance)` with `PRIMARY KEY (src, dst, rel)` (F003); adding an `attrs` column is a schema bump on
  four backends and `rel` encoding breaks `rel` filtering. Instead: the FK edge is a plain
  `references` (`provenance="extracted"`), and the **column pair lives in the `columns` side table**
  (`fk_target = "table:<origin>/<schema>.<table>.<column>"` per column) and in the page's
  `## Relations` section. `wiki_schema_neighbors` joins edge + columns to return join paths with the
  column pair. An `attrs` JSON column remains a candidate for a later store schema v3 if `calls`
  edges want it too. — *Owner: Jesus*
- [x] **Live vs. DDL merge rule** — *Resolved*: **live is authoritative for facts** (columns, types,
  constraints, row_count) whenever a live sync exists for the origin; DDL ingest for the same origin
  only (a) creates pages for tables that have **no** live counterpart (`source="ddl"`), and (b) always
  contributes `defined_in` edges to the `file:` pages. Divergence between live and DDL is reported by
  `schema diff` (optionally filed to the ledger as `tech_debt`) — never resolved silently, and never
  by "newest timestamp wins", because an ingest timestamp says when we read, not which is true.
  — *Owner: Jesus*
- [x] **Where the plane lives in production** — *Resolved*: **v1 = SQLite `schema.db`** with both
  `SchemaPlaneService.from_root(root)` (shared-root policy, F004/F005) **and** `from_dir(dir)`
  (rootless, matching FEAT-569 TASK-3354's `LedgerService.from_dir()` — F023) so a `DatabaseAgent`
  without a repo can mount a shipped or volume-mounted `schema.db`. A fleet-shared
  `create_wiki_store(backend="postgres"|"arangodb")` plane is a follow-up once FEAT-569 lands;
  widening `WikiProjectConfig.backend` is deferred with it. — *Owner: Jesus*
- [x] **`maps_to` extraction (Python model → table)** — *Resolved*: **v2**, out of this feature.
  Preferred approach when it comes: derive from structural-plane `sym:` pages whose bases include
  `Model` / `BaseModel` and that declare `Meta.name` / `Meta.schema`; no decorator or registry in
  model code. — *Owner: Jesus*
- [x] **Schema history** — *Resolved*: **no archive in v1**. `sync --changed` replaces the page and
  logs `created / updated / unchanged / removed` per table; `schema diff` is the change report.
  Bitemporal history is Option D territory and a separate proposal. — *Owner: Jesus*
- [x] **Exposure to non-Claude agents** — *Resolved*: **`SchemaPlaneToolkit` only in v1** (four read
  tools, `tool_prefix="schema"`). `SQLQuerySource.prefetch_schema` (F011) and `databasequery`'s
  `dq_get_table_metadata` (F022) become plane-aware in follow-ups. — *Owner: Jesus*
