---
id: FEAT-400
title: ArangoDB as Configurable Backend for LLM Wiki (WikiToolkit)
slug: wikitoolkit-arangodb-backend
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-08-01
  summary_oneline: "Make WikiToolkit DB backend configurable — add ArangoDB alongside SQLite"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-400/
created: 2026-08-01
updated: 2026-08-01
---

# FEAT-400 — ArangoDB as Configurable Backend for LLM Wiki (WikiToolkit)

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — user-initiated feasibility analysis
> **Audit**: [`sdd/state/FEAT-400/`](../state/FEAT-400/)

---

## 0. Origin

The LLM Wiki retrieval plane (`WikiToolkit`) currently uses SQLite as its
sole production backend (`InMemoryWikiStore` exists for testing). The goal
is to make the database backend configurable via `.parrot/wiki.json` so
teams can point their wiki at a centralized ArangoDB instance instead of
local SQLite — enabling shared, server-hosted knowledge graphs across
repositories and agents.

> Make WikiToolkit's DB abstraction configurable so `.parrot/wiki.json`
> can specify ArangoDB credentials for a centralized instance. Currently
> SQLite-only; GraphIndex added ArangoDB support via `OntologyGraphStore`
> but the wiki retrieval plane doesn't use it.

**Initial signals**:
- Verbs: "configurable", "add" → feature enrichment
- Named entities: WikiToolkit, ArangoDB, SQLite, `.parrot/wiki.json`, `OntologyGraphStore`
- Components: `parrot.knowledge.wiki`, `parrot.knowledge.ontology`
- Acceptance criteria provided: no (exploratory)

---

## 1. Synthesis Summary

The `BaseWikiStore` abstraction is already well-factored with two working
backends (`SQLiteWikiStore` and `InMemoryWikiStore`) proving the 15-method
contract is backend-agnostic. Every consumer — `WikiCombinedSearch`,
`WikiIngestOrchestrator`, `LLMWikiToolkit`, the CLI, and the export modules
— operates exclusively through this abstract interface. The `asyncdb`
driver (v2.15.9) already provides `create_arangosearch_view`,
`fulltext_search` (BM25), `vector_search` (cosine), and `hybrid_search`
methods. The existing `ArangoDBStore` in ai-parrot-embeddings and
`OntologyGraphStore` in the ontology subsystem provide battle-tested
patterns for view creation, connection management, and UPSERT. This is a
clean additive extension — no architectural changes needed.

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-400/findings/`.

### 2.1 Localization

| # | Path | Symbol | Role | Evidence |
|---|------|--------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | `BaseWikiStore` | ABC defining 15 abstract methods — the contract any backend must implement | F001 |
| 2 | `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | `SQLiteWikiStore` | Current production backend — aiosqlite + FTS5/BM25 | F001 |
| 3 | `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | `create_wiki_store()` | Factory function — sole construction point for stores | F001 |
| 4 | `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | `rank_by_cosine()` | Shared brute-force cosine helper, reusable by ArangoDB backend | F001 |
| 5 | `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | `WikiProjectConfig` | Config model — `backend: Literal["sqlite", "memory"]` needs extension | F001, F003 |
| 6 | `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | `SourceCollectionManager` | Source metadata persistence — separate from wiki store, needs new backend | F003 |
| 7 | `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | `LLMWikiToolkit.__init__` | Wiring — maps config backend to store + sources construction | F003 |
| 8 | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | `_resolve_read_store`, `_make_sources` | CLI — backend option routing and store resolution | F003 |
| 9 | `packages/ai-parrot/src/parrot/knowledge/wiki/search.py` | `WikiCombinedSearch` | Type annotation: uses `WikiStore` alias instead of `BaseWikiStore` | F001 |
| 10 | `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py` | `WikiIngestOrchestrator` | Type annotation: same `WikiStore` → `BaseWikiStore` fix needed | F001 |
| 11 | `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` | `OntologyGraphStore` | Reusable ArangoDB wrapper — connection, tenant isolation, UPSERT | F002 |
| 12 | `packages/ai-parrot-embeddings/src/parrot/stores/arango.py` | `ArangoDBStore` | Reference — ArangoSearch view creation, FTS, vector, hybrid search | F004 |

### 2.2 Constraints Discovered

- **Async/sync boundary.** `SourceCollectionManager` uses synchronous
  `sqlite3` connections (called via `asyncio.to_thread` in async contexts).
  The `asyncdb` ArangoDB driver is fully async. A new ArangoDB backend for
  SourceCollectionManager must be async, which means the public interface
  either gains async variants or the sync methods wrap `asyncio.run()` /
  `loop.run_until_complete()` for backward compat.
  *Evidence*: F003

- **Shared schema bootstrap.** When `SourceCollectionManager` uses sqlite
  backend, its `__init__` runs the full `WIKI_SCHEMA_SQL` creating ALL
  tables (meta, sources, pages, edges, pages_fts, embeddings) — not just
  sources. For ArangoDB, collection creation must be decoupled from this
  shared bootstrap.
  *Evidence*: F003

- **No ArangoSearch precedent in knowledge layer.** No ArangoSearch views
  or analyzers are currently defined in the ontology/graphindex subsystem.
  The wiki ArangoDB backend would be the first user of ArangoSearch in the
  knowledge layer. However, asyncdb's driver and `ArangoDBStore` in
  ai-parrot-embeddings provide all needed methods.
  *Evidence*: F004

- **Credential pattern is established.** All ArangoDB consumers use
  `ARANGODB_HOST/PORT/USERNAME/PASSWORD/DATABASE` env vars resolved via
  navconfig. The wiki must follow the same convention.
  *Evidence*: F002

- **backwards compatibility.** Default backend must remain `"sqlite"` with
  zero config change for existing users.
  *Evidence*: F001

### 2.3 Recent History (Relevant)

No recent commits touch the wiki store abstraction or ArangoDB integration
in the knowledge layer. The `BaseWikiStore` contract has been stable since
FEAT-260 (LLM Wiki initial implementation).

---

## 3. Probable Scope

### What's New

- **`ArangoDBWikiStore(BaseWikiStore)`** — new class implementing 15 abstract
  methods via AQL queries and ArangoSearch views. Likely ~400-600 lines in a
  new file `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`.

- **ArangoSearch view** — `{wiki_name}_pages_view` with BM25 analyzer on
  `title`, `summary`, `body` fields and `identity` analyzer on `vector`
  field for cosine similarity.

- **ArangoDB collections** — `wiki_pages`, `wiki_edges`, `wiki_sources`,
  `wiki_embeddings`, `wiki_meta` (prefixed to avoid collision with ontology
  collections).

- **`ArangoDBSourceManager`** — new SourceCollectionManager backend storing
  source metadata in a `wiki_sources` collection in the same ArangoDB
  database.

### What Changes

- **`WikiProjectConfig.backend`** — extend `Literal["sqlite", "memory"]` to
  `Literal["sqlite", "memory", "arangodb"]`. Add optional connection fields:
  `arango_url`, `arango_database`, `arango_credentials_env`.
  *Evidence*: F001, F003

- **`create_wiki_store()`** — add `elif backend == "arangodb"` branch
  importing and returning `ArangoDBWikiStore`.
  *Evidence*: F001

- **`LLMWikiToolkit.__init__`** — add wiring for `"arangodb"` backend in
  the SourceCollectionManager selection logic.
  *Evidence*: F003

- **`cli.py`** — `_resolve_read_store` and `_make_sources` need an
  `"arangodb"` branch.
  *Evidence*: F003

- **`search.py`** — change type annotation from `WikiStore` to
  `BaseWikiStore` (functional no-op at runtime).
  *Evidence*: F001

- **`ingest.py`** — same type annotation fix.
  *Evidence*: F001

### What's Untouched (Non-Goals)

- **SQLite migration tooling** — no tooling to migrate existing SQLite wikis
  to ArangoDB (future feature).
- **ArangoDB cluster/replication config** — deployment topology is the
  operator's responsibility.
- **Multi-tenant wiki isolation** — single `wiki_name` per config; no
  tenant-level partitioning within one wiki.
- **Native ArangoDB vector index (APPROX_NEAR)** — use asyncdb's dot-product
  approach initially; native vector index is an optimization pass.
- **Commit/audit/revert protocol** — SQLitePersistence has it in GraphIndex
  but it's not part of the wiki store contract.

### Patterns to Follow

- **asyncdb connection pattern** — `AsyncDB("arangodb", params=...)` +
  `await db.connection()` as used in `OntologyGraphStore`.
  *Evidence*: F002

- **ArangoSearch view creation** — `db.create_arangosearch_view()` with
  `links` dict specifying analyzer per field, as used in `ArangoDBStore`.
  *Evidence*: F004

- **AQL UPSERT** — `UPSERT {_key: @key} INSERT doc UPDATE doc IN @@coll`
  with batch+fallback as in `OntologyGraphStore.upsert_nodes()`.
  *Evidence*: F002

- **BM25 full-text search** — `ANALYZER(doc.field IN TOKENS(@query, "text_en"), "text_en")`
  + `BM25(doc)` scoring as in asyncdb's `fulltext_search()`.
  *Evidence*: F004

- **Credential resolution** — `ARANGODB_*` env vars via navconfig, same as
  all other ArangoDB consumers in the codebase.
  *Evidence*: F002

### Integration Risks

- **Async/sync bridging for SourceCollectionManager**: the current interface
  is sync; ArangoDB via asyncdb is async. Mitigation: make the ArangoDB
  source backend async and use `asyncio.to_thread` in reverse (or provide
  async variants on the SourceCollectionManager interface).
  *Evidence*: F003

- **ArangoSearch analyzer choice**: SQLite FTS5 uses `unicode61` tokenizer
  (language-agnostic). ArangoSearch's `text_en` analyzer is English-specific.
  Mitigation: make the analyzer configurable in `WikiProjectConfig` with a
  sensible default (e.g., `text_en` for English codebases, `text_es` for
  Spanish, or `identity` for language-agnostic).
  *Evidence*: F004

- **Connection lifecycle in CLI**: the CLI currently opens/closes SQLite
  synchronously per command. ArangoDB requires async connection setup.
  Mitigation: use `asyncio.run()` wrapper in CLI commands (already done in
  other CLI modules like `parrot claude`).
  *Evidence*: F003

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | BaseWikiStore contract is sufficient for ArangoDB | F001 | high | 15 abstract methods fully decoupled from SQLite; InMemoryWikiStore proves it |
| C2 | InMemoryWikiStore proves abstraction completeness | F001 | high | It implements all 15 methods with RAM+TF-IDF — no SQLite anywhere |
| C3 | asyncdb driver has all needed ArangoSearch methods | F004 | high | `fulltext_search`, `vector_search`, `hybrid_search`, `create_arangosearch_view` confirmed in driver source |
| C4 | ArangoDBStore patterns directly reusable for view creation | F004 | high | View links dict, analyzer config, auto-creation on connect — all proven |
| C5 | OntologyGraphStore connection pattern reusable | F002 | high | `AsyncDB("arangodb", params=...)` + tenant isolation via `use()` — battle-tested |
| C6 | No consumer depends on SQLite-specific behavior | F001, F003 | high | Consumers only call BaseWikiStore methods; no raw SQL outside SQLiteWikiStore |
| C7 | CLI --backend flag plumbed for arbitrary strings | F003 | high | `_resolve_read_store` already accepts `backend_opt: Optional[str]` |
| C8 | SourceCollectionManager can use ArangoDB collection | F003 | medium | Requires async/sync bridging; JSON sidecar was the fallback if this proves complex |

Distribution: **7** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Should the ArangoDB wiki use a dedicated database or share the
  ontology database?** — *Resolved*: Configurable. Default to a dedicated
  `wiki_{wiki_name}` database, but allow sharing via `arango_database`
  config field.
  *Resolves claims*: scope

- [x] **How should SourceCollectionManager handle the ArangoDB backend?**
  — *Resolved*: ArangoDB collection (`wiki_sources`) in the same database.
  Full parity, no local files needed for a centralized wiki.
  *Resolves claims*: C8

### Unresolved (defer to spec / implementation)

- [ ] **Which ArangoSearch text analyzer should be the default?** —
  *Owner*: tbd
  *Blocks claims*: —
  *Plausible answers*: a) `text_en` (English, matches ArangoDBStore
  convention) · b) `text_es` (Spanish, matches team locale) ·
  c) configurable in wiki.json with `text_en` default

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-400`** — *Rationale*: high-confidence localization across
all 12 relevant files. The abstraction is proven with two backends. Scope is
well-bounded (one new store class + config/factory/wiring extensions). No
architectural fork to explore.

### Alternatives

- **`/sdd-brainstorm FEAT-400`** — if you want to explore alternative
  approaches (e.g., a generic "remote store" abstraction that could also
  support Postgres/MongoDB, not just ArangoDB).
- **`/sdd-task FEAT-400`** — premature; the implementation has enough moving
  parts (store, sources, config, CLI, tests) to warrant a full spec first.
- **Manual review** — not needed; research was complete (not truncated) and
  confidence is high.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-400/state.json` |
| Source (raw) | `sdd/state/FEAT-400/source.md` |
| Findings (digests) | `sdd/state/FEAT-400/findings/F001-*.md` through `F004-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-400/synthesis.json` |

**Budget consumed**:
- Research agents: 4 parallel (BaseWikiStore, OntologyGraphStore, SourceCollectionManager, ArangoSearch)
- Files read: ~35 across agents
- Wiki queries: 4 (free, not budgeted)
- Truncated: **no**

**Mode determination**: `enrichment` (inline source described a feature
addition, no bug signals).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| FEAT-ID allocated by | `scripts/sdd/reserve_ids.py` |
| Operator | Claude Opus 4.6 |
| Research method | 4 parallel Explore subagents + wiki queries |
