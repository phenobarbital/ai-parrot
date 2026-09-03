---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: GraphIndex Postgres Backend — Bitemporal Plane + One-Pass Hybrid Retrieval

**Feature ID**: FEAT-520 (reserved at proposal time — `sdd/state/FEAT-520/`; reused here, NOT re-reserved)
**Date**: 2026-09-03
**Author**: Jesus Lara (proposal research: /sdd-proposal FEAT-520)
**Status**: approved
**Target version**: next minor release
**Proposal**: `sdd/proposals/graphindex-postgres-backend.proposal.md`
**Source brainstorm**: `sdd/proposals/claude_brainstorm-graphindex-postgres.md` (decisions D1–D8)

---

## 1. Motivation & Business Requirements

### Problem Statement

GraphIndex (used by LLMwiki and OntoGraph) has SQLite and ArangoDB backends.
Neither can deliver two properties the legal-wiki work needs:

1. **Temporality as an engine property, not ingest discipline.** `tstzrange` +
   exclusion constraints make it *impossible at the database level* for two
   versions of the same concept to overlap. In Arango the invariant is ingest
   discipline; in Postgres the engine rejects the violation. This implements
   the agreed bitemporal model (valid time + transaction time) and legal-wiki
   OQ5's storage side.
2. **Hybrid retrieval in one transactional snapshot**: temporal graph
   expansion + pgvector KNN + FTS, fused with RRF in a single SQL roundtrip,
   then cross-encoder re-ranking — with the temporal filter applied to *all*
   legs before fusion (KNN never returns repealed wordings).

### Goals

- G1. A third GraphIndex persistence backend on PostgreSQL (asyncpg,
  **mandatory** — resolved U4) at functional parity with `SQLitePersistence`
  / `GraphIndexPersistence`, **including the graph commit protocol**.
- G2. A `BaseWikiStore` implementation over the **same** `graphindex.*`
  schema (resolved U1: both contracts, one shared schema).
- G3. Bitemporal, append-only versioning enforced by the engine (D1, D2)
  with zero cost on the current-time read path (D3).
- G4. Temporal API as deterministic contract methods: `as_of(t)`,
  `history(concept_id)`, `diff(concept_id, t1, t2)` (D5).
- G5. One-pass hybrid retrieval (`hybrid_retrieve`, renamed from the
  brainstorm's `hybrid_search` to avoid colliding with the existing
  `PgVectorStore.hybrid_search` — C2) with graph/KNN/FTS legs in one SQL
  statement, RRF fusion in SQL, re-ranking through the existing
  `parrot/rerankers` seam (D6).
- G6. Language-parametric FTS: per-node `lang`, tsvector populated at upsert
  time, regconfig-per-namespace as declarative config (D7).
- G7. Evidence and provenance on edges: `provenance`, `derived`, and
  `evidence_ref` as `(body_ref, byte_offset)` from day one (D4, resolved U3).

### Non-Goals (explicitly out of scope)

- Migrating existing Arango graphs — **fresh ingests only in v1**
  (resolved U5); Arango tenants stay on Arango.
- Reusing or modifying `PgVectorStore` (`ai-parrot-embeddings`
  `stores/postgres.py`) — it is SQLAlchemy-based and explicitly excluded
  (resolved U4). Embeddings for this backend live in the `graphindex.*`
  schema.
- Temporal retrofit of the SQLite/Arango backends — they keep serving
  `t = now()` semantics; temporal methods raise `NotImplementedError` (D5).
- ParadeDB `pg_search` / true BM25 in Postgres — `ts_rank_cd` suffices for
  top-k context assembly (brainstorm risk table); revisit only on measured
  ranking-quality problems.
- SQLAlchemy anywhere in this backend (D8).

---

## 2. Architectural Design

### Overview

One Postgres schema, `graphindex.*`, serves **two existing contracts** from
a shared bitemporal data plane:

- **`PostgresPersistence`** (`parrot/knowledge/graphindex/persist_postgres.py`)
  mirrors the `GraphIndexPersistence` public API — `persist_graph`,
  `replace_document_slice`, `load_graph`, `is_stale`, plus the commit
  protocol (`apply_update`, `get_commit`, `list_commits`, `revert_commit`) —
  and adds the temporal contract (`as_of`, `history`, `diff`) and
  `hybrid_retrieve`. Where Arango serializes writers with a per-tenant
  `asyncio.Lock` and SQLite with WAL, Postgres uses real transactions: the
  commit + pre-images + mutations of `apply_update` are ONE transaction.
- **`PostgresWikiStore(BaseWikiStore)`**
  (`parrot/knowledge/wiki/postgres_store.py`) implements the wiki retrieval
  plane over the same tables, wired into `create_wiki_store` via a new
  explicit `backend == "postgres"` branch (lazy import — the exact ArangoDB
  precedent at `wiki/store.py:1838`).

Writes are **append-only** (D2): a correction closes the previous version's
`validity` range and inserts a new row in the same transaction; content is
never UPDATEd. The engine enforces non-overlap via an exclusion constraint
(D1). The current-time read path uses partial indexes
(`WHERE upper_inf(validity)`) so non-temporal queries never touch the GiST
temporal index (D3).

#### The U1 mapping: wiki pages ↔ graph nodes on one schema

The two planes share identity and versions but keep plane-specific columns:

| Concept | `graphindex.nodes` (identity) | `graphindex.node_versions` (state) |
|---|---|---|
| GraphIndex `UniversalNode` | `concept_id` := `node_id` (stable in graphindex), `category` := `kind` (NodeKind value), `namespace` from domain/tenant | `title`, `summary`, `body_ref` := `content_ref` (markdown stays on disk), `provenance`, `assertion` jsonb, `domain_tags` jsonb |
| Wiki `WikiPageRecord` | `concept_id` := `concept_id` (stable), `category` := `category` (open string), `node_id` := volatile `node_id` | `title`, `summary`, **`body`** (inline text — the wiki contract stores the full body in the DB, `store.py:308`), `origin`, `asserted_by`, `updated_at` (caller-preserving semantics per FEAT-461), `content_hash`, `token_count` |

Key reconciliations (this is the design decision the proposal deferred to
this spec):

1. **Body storage**: `node_versions` carries BOTH `body text NULL` (wiki
   plane — body in DB) and `body_ref text NULL` (graph plane — markdown on
   disk, reranker reads the file). At most one is expected per row; neither
   is required.
2. **Identity**: `concept_id` is the PK for both planes. GraphIndex's
   `node_id` IS stable (it is the SQLite PK today), so it maps directly to
   `concept_id`; the wiki's *volatile* `node_id` maps to `nodes.node_id`
   (nullable, secondary lookup only — same semantics as `WikiPageRecord`).
3. **Provenance vs origin**: distinct columns. `provenance`
   (extracted/inferred/derived — graph semantics, D4) and `origin`
   (ingest/authored/memory — wiki semantics, `store.py:311`). Neither plane
   writes the other's column.
4. **Edges**: one `graphindex.edges` table. `rel` holds `EdgeKind` values
   for the graph plane and the wiki's edge-kind strings for the wiki plane;
   `confidence REAL NULL` with the `UniversalEdge` invariant (confidence set
   iff provenance = inferred) enforced by a CHECK constraint — the engine
   carries the Pydantic validator's rule (`schema.py:217`).
5. **Wiki `updated_at` / LWW**: `tx_from` is the transaction stamp; a
   separate `updated_at timestamptz NULL` preserves the wiki's
   caller-supplied-wins semantics (sync/TASK-2466 relies on it — do NOT
   conflate it with `tx_from`).
6. **Symbols (wiki schema v2)**: a `graphindex.symbols` table mirroring the
   SQLite `symbols` table serves `upsert_symbols`/`symbols_for`/
   `find_symbols`/`search_symbols_fts`/`page_hashes` (non-abstract on
   `BaseWikiStore`, `store.py:572` — Arango precedent allows graceful
   degradation, but this backend implements them: Module 8).

### Component Diagram

```
                    ┌──────────────────────────────────────────────┐
                    │        graphindex.* (one Postgres schema)     │
                    │  nodes ── node_versions (bitemporal, EXCLUDE) │
                    │  edges (validity, evidence_ref)               │
                    │  embeddings (pgvector, per version)           │
                    │  symbols · files · commits · commit_items     │
                    └───────▲──────────────────────▲───────────────┘
                            │ asyncpg pool (pg_base)│
        ┌───────────────────┴────────┐   ┌──────────┴──────────────────┐
        │ PostgresPersistence        │   │ PostgresWikiStore           │
        │ (graphindex plane)         │   │ (BaseWikiStore impl)        │
        │ persist_graph / slice /    │   │ upsert_pages / search_fts / │
        │ commit protocol /          │   │ search_vector / neighbors / │
        │ as_of · history · diff /   │   │ symbols / dumps / stats     │
        │ hybrid_retrieve ───────────┼─┐ └──────────▲──────────────────┘
        └───────▲────────────────────┘ │            │
                │ factory.py            │ rerank     │ create_wiki_store
        GraphPublisher / toolkit        ▼            │  backend="postgres"
                              parrot/rerankers (AbstractReranker,
                              LocalCrossEncoderReranker — existing seam)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GraphIndexPersistence` (`persist.py`) | API mirror | `PostgresPersistence` implements the same public surface (duck-typed, like `SQLitePersistence`) |
| `SQLitePersistence` (`persist_sqlite.py`) | pattern template | schema/migration/staleness (`files` table) and commit-protocol shape |
| `GraphPublisher` (`publish.py`) | consumer | works unchanged over the mirrored commit protocol |
| `graphindex/factory.py` | extends | new construction path for the Postgres backend |
| `BaseWikiStore` + `create_wiki_store` (`wiki/store.py:415,1795`) | implements + extends | new `backend == "postgres"` branch (lazy import), Arango precedent |
| `parrot/rerankers` (`AbstractReranker`, factory) | uses | `hybrid_retrieve` re-ranking leg; copy `HybridPageIndexSearch._apply_reranker` fallback semantics |
| `tests/knowledge/wiki/test_store.py` fixture | extends | `postgres` param, live-DB-gated by env (Arango precedent) |
| navconfig | config | DSN + regconfig-per-namespace mapping (declarative, D7) |
| `parrot_tools/graphindex/toolkit.py` | extends (Module 9) | mono-purpose tools for `as_of`/`history`/`diff`/`hybrid_retrieve` |

### Data Models

New Pydantic models (in `persist_postgres.py` or a small `pg_models.py`):

```python
class NodeVersionRow(BaseModel):
    """One row of graphindex.node_versions, as returned by history()/as_of()."""
    version_id: int
    concept_id: str
    valid_from: datetime
    valid_to: Optional[datetime]        # None == open range (current)
    tx_from: datetime
    title: str
    summary: str = ""
    body: Optional[str] = None          # wiki plane
    body_ref: Optional[str] = None      # graph plane (markdown on disk)
    provenance: str = "extracted"
    derived: bool = False

class TemporalDiff(BaseModel):
    """Structured output of diff(concept_id, t1, t2) — LLM-consumable,
    never 'compare these two texts'."""
    concept_id: str
    t1: datetime
    t2: datetime
    version_changes: list[dict]         # closed/opened version rows
    edges_added: list[dict]             # incident edges valid at t2, not t1
    edges_removed: list[dict]           # incident edges valid at t1, not t2

class HybridCandidate(BaseModel):
    """One fused candidate from hybrid_retrieve (pre- or post-rerank)."""
    concept_id: str
    version_id: int
    title: str
    score: float
    signals: dict[str, float]           # per-leg RRF contributions + graph depth
    body_ref: Optional[str] = None
    evidence: list[dict] = []           # (body_ref, byte_offset) pairs from edges
```

### Schema DDL (normative draft — Module 1 owns the final form)

```sql
CREATE SCHEMA IF NOT EXISTS graphindex;
-- requires: CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE graphindex.nodes (             -- identity (one row per concept)
  concept_id   text PRIMARY KEY,
  namespace    text NOT NULL DEFAULT '',    -- 'legal:core', 'legal:laboral', …
  category     text NOT NULL,               -- NodeKind value (graph) | open category (wiki)
  node_id      text,                        -- volatile position (wiki), NULL for graph plane
  lang         text NOT NULL DEFAULT 'simple',
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE graphindex.node_versions (     -- state: append-only, bitemporal
  version_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  concept_id   text NOT NULL REFERENCES graphindex.nodes ON DELETE CASCADE,
  validity     tstzrange NOT NULL DEFAULT tstzrange(now(), null),
  tx_from      timestamptz NOT NULL DEFAULT now(),
  title        text NOT NULL,
  summary      text NOT NULL DEFAULT '',
  body         text,                        -- wiki plane (body-in-DB contract)
  body_ref     text,                        -- graph plane (markdown on disk)
  source_id    text,                        -- wiki sources / graph source_uri
  content_hash text,
  token_count  integer NOT NULL DEFAULT 0,
  fts          tsvector,                    -- populated at upsert with nodes.lang regconfig (D7)
  provenance   text NOT NULL DEFAULT 'extracted',
  derived      boolean NOT NULL DEFAULT false,
  origin       text,                        -- wiki plane: ingest|authored|memory
  asserted_by  text,
  updated_at   timestamptz,                 -- wiki LWW stamp — caller-preserving (FEAT-461)
  assertion    jsonb,
  domain_tags  jsonb,
  EXCLUDE USING gist (concept_id WITH =, validity WITH &&)   -- D1: engine-enforced
);
CREATE INDEX nv_current  ON graphindex.node_versions (concept_id) WHERE upper_inf(validity);  -- D3
CREATE INDEX nv_validity ON graphindex.node_versions USING gist (validity);
CREATE INDEX nv_fts      ON graphindex.node_versions USING gin (fts);

CREATE TABLE graphindex.edges (
  edge_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  src          text NOT NULL,
  dst          text NOT NULL,
  rel          text NOT NULL,               -- EdgeKind value | wiki edge kind
  validity     tstzrange NOT NULL DEFAULT tstzrange(now(), null),
  tx_from      timestamptz NOT NULL DEFAULT now(),
  provenance   text NOT NULL DEFAULT 'extracted',
  derived      boolean NOT NULL DEFAULT false,
  confidence   real,
  CHECK ((provenance = 'inferred') = (confidence IS NOT NULL)),  -- schema.py:217 invariant
  assertion    jsonb,
  evidence_ref jsonb,                       -- U3: {"body_ref": text, "byte_offset": int} (nullable)
  source_id    text                         -- replace_source_slice scope
);
CREATE INDEX e_src ON graphindex.edges (src, rel) WHERE upper_inf(validity);
CREATE INDEX e_dst ON graphindex.edges (dst, rel) WHERE upper_inf(validity);
CREATE INDEX e_validity ON graphindex.edges USING gist (validity);

CREATE TABLE graphindex.embeddings (        -- U4: in-schema, asyncpg-managed
  concept_id   text NOT NULL,
  version_id   bigint NOT NULL REFERENCES graphindex.node_versions ON DELETE CASCADE,
  model        text NOT NULL DEFAULT '',
  embedding    vector NOT NULL,             -- dimension fixed per deployment config
  PRIMARY KEY (version_id, model)
);
-- HNSW/IVFFlat index creation is config-driven (dimension known at migrate time).

CREATE TABLE graphindex.symbols ( ... );    -- mirrors wiki SQLite symbols (Module 8)
CREATE TABLE graphindex.files (             -- staleness, persist_sqlite.py:41 parity
  source_uri text PRIMARY KEY, mtime double precision NOT NULL,
  sha1 text NOT NULL, indexed_at timestamptz NOT NULL
);
CREATE TABLE graphindex.commits (           -- commit protocol, persist_sqlite.py:82 parity
  commit_id text PRIMARY KEY, seq bigint GENERATED ALWAYS AS IDENTITY,
  op text NOT NULL, agent_id text, run_id text, asserted_by text NOT NULL,
  reason text, committed_at timestamptz NOT NULL DEFAULT now(),
  payload jsonb NOT NULL, reverted_at timestamptz
);
CREATE TABLE graphindex.commit_items (
  commit_id text NOT NULL REFERENCES graphindex.commits,
  item_type text NOT NULL, item_key text NOT NULL, collection text, prior jsonb,
  PRIMARY KEY (commit_id, item_type, item_key)
);
```

### New Public Interfaces

```python
# parrot/knowledge/graphindex/persist_postgres.py
class PostgresPersistence:
    """Third GraphIndex backend. Public API mirrors GraphIndexPersistence
    (persist.py) exactly — duck-typed like SQLitePersistence — plus the
    temporal and hybrid extensions below."""

    def __init__(self, dsn: str, *, pool: Optional[asyncpg.Pool] = None,
                 schema: str = "graphindex") -> None: ...

    # --- parity surface (mirrors persist.py / persist_sqlite.py) ---
    async def persist_graph(self, ctx, nodes, edges) -> dict[str, Any]: ...
    async def replace_document_slice(self, ctx, document_uri, nodes, edges) -> dict[str, Any]: ...
    async def is_stale(self, ctx, source_uri, mtime, sha1) -> bool: ...
    async def load_graph(self, ctx) -> tuple[list[UniversalNode], list[UniversalEdge]]: ...
    async def apply_update(self, ctx, update: GraphUpdate) -> CommitReceipt: ...
    async def get_commit(self, ctx, commit_id) -> Optional[dict[str, Any]]: ...
    async def list_commits(self, ctx, run_id=None, agent_id=None, limit=50) -> list[dict]: ...
    async def revert_commit(self, ctx, commit_id) -> dict[str, Any]: ...

    # --- temporal contract (D5) — new, Postgres-only in v1 ---
    async def as_of(self, ctx, t: datetime) -> tuple[list[UniversalNode], list[UniversalEdge]]: ...
    async def history(self, ctx, concept_id: str) -> list[NodeVersionRow]: ...
    async def diff(self, ctx, concept_id: str, t1: datetime, t2: datetime) -> TemporalDiff: ...

    # --- one-pass hybrid (D6) — deliberately NOT named hybrid_search (C2) ---
    async def hybrid_retrieve(
        self, ctx, *,
        query_embedding: Optional[list[float]] = None,
        fts_terms: Optional[str] = None,
        seeds: Optional[list[str]] = None,          # concept_ids from the ontological router
        as_of: Optional[datetime] = None,           # None → now(); applied to ALL legs
        weights: Optional[dict[str, float]] = None, # rrf leg weights + depth decay
        limit: int = 20,
        reranker: Optional[AbstractReranker] = None,
        rerank_top_k: int = 10,
    ) -> list[HybridCandidate]: ...

# parrot/knowledge/wiki/postgres_store.py
class PostgresWikiStore(BaseWikiStore):
    """Wiki retrieval plane over graphindex.* — full abstract surface plus
    the schema-v2 symbol methods. Constructed by create_wiki_store(
    backend='postgres', dsn=..., wiki_name=...)."""
```

Temporal semantics on the other backends (D5): `SQLitePersistence` /
`GraphIndexPersistence` do NOT grow `as_of/history/diff` in v1 — callers
feature-detect via `hasattr` (the established duck-typing between the three
backends). The toolkit registers the temporal tools only when the bound
persistence exposes them.

---

## 3. Module Breakdown

### Module 1: Schema, migration, and connection base
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py`
- **Responsibility**: `graphindex.*` DDL (normative draft above),
  `PG_SCHEMA_VERSION`, idempotent versioned migration in the
  `_MIGRATION_COLUMNS` style (`wiki/store.py:166`, `persist_sqlite.py:109`),
  asyncpg pool creation/config via navconfig (DSN key, pool sizing,
  embedding dimension, regconfig-per-namespace map), pgvector codec
  registration (`pgvector.asyncpg.register_vector`).
- **Depends on**: nothing new.

### Module 2: `PostgresPersistence` — parity surface (non-temporal reads)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py`
- **Responsibility**: `persist_graph`, `replace_document_slice` (one
  transaction: close/delete versions+edges by `source_id`, reinsert),
  `is_stale` (files table), `load_graph` (current versions only —
  `upper_inf(validity)`). Bitemporal WRITE semantics from day one
  (close-and-insert, never UPDATE), even though this module's reads are
  current-time only. FTS column populated at upsert with the node's `lang`
  regconfig (D7).
- **Depends on**: Module 1.

### Module 3: Commit protocol on real transactions
- **Path**: same file as Module 2.
- **Responsibility**: `apply_update`/`get_commit`/`list_commits`/
  `revert_commit` at behavioral parity with
  `test_persist_commit_protocol.py`, with pre-images + commit row + mutations
  in ONE transaction (no per-tenant asyncio.Lock needed for atomicity;
  keep `seq`-based revert-conflict refusal identical to the siblings).
- **Depends on**: Module 2.

### Module 4: Temporal plane — `as_of` / `history` / `diff`
- **Path**: same file; `TemporalDiff`/`NodeVersionRow` models.
- **Responsibility**: D5 contract methods. `as_of` = snapshot read with
  `validity @> $t` on versions AND edges; `history` = ordered version rows;
  `diff` = range operations over `node_versions` + incident-edge deltas
  between t1/t2, returning structured `TemporalDiff`. Exclusion-constraint
  violations surface as explicit ingest errors (the rejection IS the
  feature — brainstorm risk table).
- **Depends on**: Module 2.

### Module 5: `PostgresWikiStore` over the shared schema
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py`
- **Responsibility**: full `BaseWikiStore` abstract surface mapped per the
  U1 table in §2 (body-in-DB, `origin`, caller-preserving `updated_at`,
  `content_hash`, volatile `node_id`); `replace_source_slice` scoped by
  `source_id`; `search_fts` over the shared `fts` column; `search_vector`
  over `graphindex.embeddings`; `neighbors`/`broken_edges`/`orphan_sources`
  /`stats`/dumps. New `backend == "postgres"` branch in `create_wiki_store`
  (lazy import, `wiki/store.py:1830-1848` pattern).
- **Depends on**: Modules 1, 2 (write path shares the close-and-insert
  helpers).

### Module 6: Embeddings in-schema + KNN leg
- **Path**: `pg_schema.py` (table) + `persist_postgres.py` (API)
- **Responsibility**: `graphindex.embeddings` with per-version rows
  (temporal filter = join to `node_versions.validity`), upsert path for the
  graphindex embed stage and `PostgresWikiStore.upsert_embedding`; ANN
  index creation (config-driven dimension; pgvector ≥ 0.8 for iterative
  index scans — OQ3 mitigation).
- **Depends on**: Modules 1, 2, 5.

### Module 7: `hybrid_retrieve` — one-pass SQL + re-ranking
- **Path**: `persist_postgres.py` (+ SQL builder helpers)
- **Responsibility**: single SQL statement with CTEs: (a) recursive
  temporal graph expansion from `seeds` (depth ≤ 5, `validity @> $as_of`
  each hop, depth carried as a weighted signal, not a filter); (b) pgvector
  KNN joined to version validity; (c) FTS `ts_rank_cd` leg; RRF fusion
  `Σ w_i/(60 + rank_i)` in SQL (constant matching `_RRF_K=60`,
  `pageindex/hybrid_search.py`); re-ranking OUTSIDE SQL via
  `AbstractReranker.rerank(query, docs, top_n)` reading full markdown from
  `body_ref`/`body` — copy `_apply_reranker` fallback semantics (reranker
  failure → fused order). Includes the **OQ3 spike** as its first task:
  benchmark KNN-under-graph-filter both directions on a realistic corpus
  before freezing CTE order.
- **Depends on**: Modules 4, 6.

### Module 8: Wiki symbol surface (schema v2 parity)
- **Path**: `pg_schema.py` (symbols table) + `postgres_store.py`
- **Responsibility**: `upsert_symbols`, `symbols_for`, `find_symbols`,
  `search_symbols_fts`, `page_hashes` mirroring the SQLite semantics
  (`wiki/store.py:577-720`); `pg_trgm`/`simple` regconfig for symbol FTS.
- **Depends on**: Module 5.

### Module 9: Factory, toolkit tools, tests wiring, docs
- **Path**: `graphindex/factory.py`, `parrot_tools/graphindex/toolkit.py`,
  `tests/`, `docs/graphindex.md`
- **Responsibility**: Postgres construction path in the graphindex factory;
  mono-purpose toolkit tools (`graph_as_of`, `graph_history`, `graph_diff`,
  hybrid retrieval tool) registered only when the bound persistence exposes
  the temporal surface (D5: separate tools, never modal parameters);
  `postgres` param in the wiki store fixture (live-DB-gated); docs +
  CHANGELOG.
- **Depends on**: Modules 4, 5, 7.

---

## 4. Test Specification

### Unit / behavioral tests

| Test | Module | Description |
|---|---|---|
| `test_pg_schema_migration_idempotent` | 1 | migrate twice → identical schema; version stamp recorded |
| `test_persist_graph_roundtrip_pg` | 2 | `persist_graph` → `load_graph` model equality (parity with `test_persist.py`) |
| `test_replace_document_slice_atomic_pg` | 2 | slice replace is one transaction; concurrent reader never sees partial state |
| `test_append_only_correction` | 2 | re-upsert same concept → old version's validity closed, new row inserted, no UPDATE of content |
| `test_exclusion_constraint_rejects_overlap` | 4 | overlapping validity for same concept_id → explicit ingest error (the rejection is the feature) |
| `test_as_of_snapshot` | 4 | nodes+edges valid at t; repealed versions/edges excluded |
| `test_history_ordering` | 4 | version rows ordered, ranges contiguous |
| `test_diff_structured` | 4 | `TemporalDiff` lists version + incident-edge deltas between t1/t2 |
| `test_commit_protocol_parity_pg` | 3 | port of `test_persist_commit_protocol.py` scenarios (apply/get/list/revert, seq conflict refusal) |
| `test_edge_confidence_check` | 2 | CHECK mirrors `UniversalEdge` validator (inferred ⇔ confidence) |
| `test_fts_lang_per_namespace` | 2 | `legal:*` → spanish regconfig; `sym:`/code → simple; queried via `search_fts`/FTS leg |
| `test_wiki_store_contract_pg` | 5 | existing `test_store.py` suite green with `postgres` param |
| `test_wiki_updated_at_preserved` | 5 | caller-supplied `updated_at` survives upsert verbatim (FEAT-461/TASK-2466 semantics) |
| `test_symbols_surface_pg` | 8 | symbol methods parity with SQLite semantics |
| `test_hybrid_retrieve_legs` | 7 | each leg independently, then fused; `as_of` filters all three legs pre-fusion |
| `test_hybrid_rrf_fusion_sql` | 7 | RRF scores match `Σ w/(60+rank)` reference computation |
| `test_hybrid_rerank_fallback` | 7 | reranker failure → fused order preserved (`_apply_reranker` semantics) |
| `test_evidence_ref_roundtrip` | 2 | `(body_ref, byte_offset)` persisted and returned in `HybridCandidate.evidence` |

### Integration tests

| Test | Description |
|---|---|
| `test_graphpublisher_over_postgres` | `GraphPublisher` works unchanged over `PostgresPersistence` (agent write path) |
| `test_create_wiki_store_postgres` | factory branch constructs the store; unknown-backend error message lists `postgres` |
| `test_ingest_then_hybrid_e2e` | ingest a small corpus → `hybrid_retrieve` with seeds returns temporally-valid, reranked candidates |

### Test data / fixtures

```python
# All Postgres tests are live-DB-gated, Arango precedent:
GRAPHINDEX_PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN")
pytestmark = pytest.mark.skipif(not GRAPHINDEX_PG_DSN, reason="needs live Postgres")

@pytest.fixture
async def pg_persistence(tmp_schema):    # per-test schema name → parallel-safe, DROP SCHEMA CASCADE teardown
    ...

# wiki suite: extend the existing fixture (tests/knowledge/wiki/test_store.py:29)
@pytest.fixture(params=["sqlite", "memory",
                        pytest.param("postgres", marks=needs_pg)])
def store(request, tmp_path): ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `PostgresPersistence` passes behavioral parity: the `test_persist.py`
      and `test_persist_commit_protocol.py` scenarios green on Postgres
      (live-DB-gated).
- [ ] The existing wiki contract suite (`tests/knowledge/wiki/test_store.py`)
      passes with the new `postgres` fixture param; `sqlite`/`memory` params
      remain byte-identical in behavior (no regression).
- [ ] Engine-enforced non-overlap: inserting two versions of one
      `concept_id` with overlapping `validity` raises an explicit error from
      the exclusion constraint (D1) — covered by a test.
- [ ] Append-only: no code path issues `UPDATE` on `node_versions.body/title/
      summary`; corrections close-and-insert (D2) — verified by test +
      review.
- [ ] Current-path cost: `load_graph`/`search_fts`/`neighbors` plans use the
      partial `upper_inf(validity)` indexes (D3) — verified once via
      `EXPLAIN` in the OQ3 spike notes.
- [ ] `as_of`/`history`/`diff` return deterministic, structured results
      (D5); the other two backends remain untouched, and the toolkit exposes
      temporal capabilities as separate mono-purpose tools only when present.
- [ ] `hybrid_retrieve` executes graph+KNN+FTS as ONE SQL statement (D6),
      applies `as_of` to all legs pre-fusion, fuses with RRF (k=60) in SQL,
      and re-ranks via `AbstractReranker` with fused-order fallback.
- [ ] FTS regconfig is per-namespace declarative config; `lang` column
      drives `to_tsvector` at upsert (D7) — no regconfig hardcoded in SQL
      strings.
- [ ] Edges carry `provenance`, `derived`, and nullable `evidence_ref`
      `{"body_ref", "byte_offset"}` (D4/U3); the CHECK constraint mirrors
      the `UniversalEdge` confidence⇔inferred invariant.
- [ ] The backend contains **zero** SQLAlchemy imports and does not import
      from `parrot.stores.postgres` (U4) — grep-verifiable.
- [ ] No breaking changes to existing public APIs (`BaseWikiStore`,
      `GraphIndexPersistence`, `create_wiki_store` signatures unchanged;
      additive only).
- [ ] Docs updated: `docs/graphindex.md` backend matrix + temporal/hybrid
      sections; CHANGELOG entry.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-09-03 against
> `dev` @ `9c06c3c22`. Full research audit: `sdd/state/FEAT-520/`.

### Verified Imports

```python
from parrot.knowledge.graphindex.schema import (      # schema.py — verified
    AssertionMeta,      # :100 (asserted_by: str at :120)
    CommitReceipt,      # :269
    EdgeKind,           # :64
    GraphUpdate,        # :233 (asserted_by :263)
    NodeKind,           # :36
    Provenance,         # :18
    UniversalEdge,      # :184
    UniversalNode,      # :149
)
from parrot.knowledge.ontology.schema import TenantContext   # used by both persist backends (persist.py imports it)
from parrot.knowledge.wiki.store import (
    BaseWikiStore,          # store.py:415
    WikiPageRecord,         # store.py:299
    create_wiki_store,      # store.py:1795
    register_wiki_backend,  # store.py:401 (_EXTRA_BACKENDS at :391)
    rank_by_cosine,         # store.py:348 — shared brute-force vector ranking helper
)
from parrot.knowledge.wiki.symbols import SymbolRecord       # symbols.py:56
from parrot.rerankers.abstract import AbstractReranker       # abstract.py:35
import asyncpg    # already used in core: parrot/core/hooks/postgres.py, parrot/eval/sink.py,
                  # parrot/knowledge/retrieval/pin.py, parrot/knowledge/ontology/concept_catalog/seed.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py  (Arango backend — the API to mirror)
class GraphIndexPersistence:
    def __init__(self, graph_store: OntologyGraphStore) -> None
    async def persist_graph(self, ctx: TenantContext, nodes: list[UniversalNode], edges: list[UniversalEdge]) -> dict[str, Any]
    async def replace_document_slice(self, ctx, document_uri: str, nodes, edges) -> dict[str, Any]
    async def load_graph(self, ctx) -> tuple[list[UniversalNode], list[UniversalEdge]]
    async def apply_update(self, ctx, update: GraphUpdate) -> CommitReceipt
    async def get_commit(self, ctx, commit_id: str) -> Optional[dict[str, Any]]
    async def list_commits(self, ctx, run_id=None, agent_id=None, limit=50) -> list[dict[str, Any]]
    async def revert_commit(self, ctx, commit_id: str) -> dict[str, Any]

# packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py  (structural template)
_SCHEMA_SQL                # :38  — nodes(:48)/edges(:65)/nodes_fts FTS5(:78)/graph_commits(:82)/graph_commit_items(:96)/files(:41)
_MIGRATION_COLUMNS         # :109 — idempotent ALTER-in pattern
class SQLitePersistence:   # :138
    async def _connect(self, ctx) -> AsyncIterator[aiosqlite.Connection]   # :173
    async def persist_graph(...)            # :263
    async def replace_document_slice(...)   # :341
    async def is_stale(self, ctx, source_uri, mtime, sha1)                 # :464
    async def load_graph(...)               # :574
    async def apply_update(...)             # :608
    async def get_commit(...)               # :785
    async def list_commits(...)             # :817
    async def revert_commit(...)            # :856

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
SCHEMA_VERSION = "2"       # :49
WIKI_SCHEMA_SQL            # :53
_MIGRATION_COLUMNS         # :166
class WikiPageRecord(BaseModel):   # :299 — concept_id(:334, required), node_id(:335, volatile),
    # title, category(:337, default "concept"), summary, body(:339 — full body IN THE DB),
    # source_id, token_count, origin(:342 — ingest|authored|memory), asserted_by,
    # updated_at(:344 — caller-preserving, FEAT-461), content_hash(:345)
class BaseWikiStore(ABC):  # :415 — abstract: upsert_pages(:434), add_edges(:437),
    # replace_source_slice(:440), delete_page(:448), upsert_embedding(:451), get_page(:455),
    # list_pages(:458), search_fts(:466), search_vector(:469), neighbors(:472), dump_pages(:480),
    # dump_edges(:483), stats(:486), orphan_sources(:490), broken_edges(:493), missing_bodies(:496)
    # NON-abstract (deliberate, :572): upsert_symbols(:577), symbols_for(:597), find_symbols(:624),
    # search_symbols_fts(:672), page_hashes(:693)
def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kwargs) -> BaseWikiStore  # :1795
    # explicit branches: sqlite(:1830), memory(:1832), arangodb(:1838 — LAZY IMPORT precedent),
    # _EXTRA_BACKENDS hook(:1849)

# packages/ai-parrot/src/parrot/rerankers/abstract.py
class AbstractReranker(ABC):   # :35
    async def rerank(self, query: str, documents: list[SearchResult],
                     top_n: Optional[int] = None) -> list[RerankedDocument]   # :50
    # CONTRACT: must NOT raise on internal failure — returns input wrapped with
    # rerank_score=NaN in original order (caller applies fallback policy).

# packages/ai-parrot/src/parrot/knowledge/graphindex/grounding.py
async def ground_claim(self, claim: str) -> GroundingResult   # :204 — evidence via
    # stable_edge_id(src, dst, kind) paths over the in-memory graph; 'contradicts' never supports.

# packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
async def build_graph_memory_toolkit(...)   # :203 — instantiates SQLitePersistence (:239) +
    # GraphPublisher(persistence, ctx) (:240); import at :33.

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py  (patterns to copy, NOT to import)
_RRF_K = 60                              # RRF constant
HybridPageIndexSearch._rrf_fuse          # Σ 1/(k + rank + 1) fusion
HybridPageIndexSearch._apply_reranker    # SearchResult docs → reranker.rerank(query, docs, top_n)
                                         # → fused-order fallback on failure
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PostgresPersistence` | `GraphPublisher` | duck-typed persistence (same surface as siblings) | `factory.py:239-240` |
| `PostgresPersistence` | graphindex factory | new construction path | `factory.py:203` |
| `PostgresWikiStore` | `create_wiki_store` | new explicit `postgres` branch, lazy import | `wiki/store.py:1838` (arangodb precedent) |
| `hybrid_retrieve` rerank leg | `AbstractReranker.rerank` | `(query, list[SearchResult], top_n)` | `rerankers/abstract.py:50` |
| wiki tests | `store` fixture | new `postgres` param | `tests/knowledge/wiki/test_store.py:29` |
| edge CHECK constraint | `UniversalEdge` validator | confidence ⇔ provenance=INFERRED | `graphindex/schema.py:217-229` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/knowledge/graphindex/persist_postgres.py`~~ — created by this feature.
- ~~`PostgresWikiStore`~~, ~~`create_wiki_store(backend="postgres")`~~ — created by this feature.
- ~~`hybrid_search` on `GraphIndexPersistence`/`SQLitePersistence`/`BaseWikiStore`~~ —
  no graph/wiki store has hybrid retrieval. **`hybrid_search` DOES exist on
  `PgVectorStore`** (`ai-parrot-embeddings/src/parrot/stores/postgres.py:1728`,
  dense+ColBERT, SQLAlchemy) — that class is EXCLUDED from this feature (U4);
  do not import from `parrot.stores.postgres` here.
- ~~temporal columns (`validity`, `tx_from`, `valid_from`) in any existing backend~~ —
  none exist anywhere; created by this feature.
- ~~`evidence`/`evidence_ref` on any existing edge storage~~ — today only
  `provenance`, `confidence`, `assertion` (see `persist_sqlite.py:65-74`).
- ~~`as_of`/`history`/`diff` on any store~~ — new contract, Postgres-only in v1.
- ~~BM25/`ts_rank` query path over Postgres~~ — the only FTS artifact is a
  hardcoded-English GIN index (`stores/postgres.py:1488`), not a seam.
- ~~`parrot/vectorstores/`~~ — long gone; vector stores are `parrot/stores/`.
- ~~a `parse()`-style shared backend enum for graphindex~~ — backend selection
  is duck-typed construction in `factory.py`, not a registry.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **asyncpg only** (U4, mandatory): pool via `asyncpg.create_pool`,
  parameterized queries (`$1`), transactions via
  `async with conn.transaction():`. Precedents: `parrot/core/hooks/postgres.py`,
  `parrot/eval/sink.py`. Zero SQLAlchemy imports (acceptance criterion).
- **Mirror-API discipline**: `persist_sqlite.py`'s docstring contract
  ("Public API mirrors GraphIndexPersistence") — keep signatures duck-type
  identical; graphindex code must not need `isinstance` checks.
- **Idempotent migration**: `PG_SCHEMA_VERSION` + `_MIGRATION_COLUMNS`-style
  ALTER-in (D8), following `wiki/store.py:1041` `_migrate`.
- **FTS population in the upsert** (D7): Postgres cannot use a variable
  regconfig in a generated column — build the `to_tsvector($lang_regconfig, ...)`
  in the INSERT from the store (the store is the single write seam);
  regconfig-per-namespace is navconfig data, not code.
- **Reranker consumption**: copy `HybridPageIndexSearch._apply_reranker`
  semantics — reranker reads full content (`body` or the file at `body_ref`),
  never the truncated row; failure → fused order.
- Async-first, Google docstrings, strict typing, `self.logger`, Pydantic for
  structured returns — house rules.

### Known Risks / Gotchas

- **KNN under graph filter can defeat HNSW** (OQ3, still open): mitigate
  with pgvector ≥ 0.8 iterative index scans; for small graph hoods
  (depth ≤ 3) exact scan wins. Module 7 STARTS with the spike (both
  directions: graph→semantic, semantic→graph) before freezing CTE order.
- **Exclusion constraint rejects badly-derived ranges** (e.g. CELLAR diffs):
  intended behavior — explicit ingest error beats a lying graph; route
  conflicts to a review queue at the ingest layer, never auto-widen ranges.
- **Dual source of temporal truth**: in this backend `node_versions` IS the
  truth; any `versions[]`-style embedded projection is a read-time view for
  API compatibility, never written independently.
- **Wiki `updated_at` vs `tx_from`**: do not conflate — sync (TASK-2466)
  depends on caller-supplied `updated_at` surviving verbatim; `tx_from` is
  always server-stamped.
- **Schema-v2 symbol surface is fresh** (TASK-2742..2751, ~Aug 2026) and may
  still move; Module 8 tracks `wiki/store.py` as the reference semantics,
  not a frozen copy.
- **Contract drift across 4 backends** (3 graphindex + wiki matrix): the
  parametrized suites (§4) are the merge gate — brainstorm risk table.
- **`pytest tests/unit` hang**: wrap suite runs in `timeout -s KILL`
  (known repo issue — suite finishes then never exits).

### Configuration References (navconfig)

| Key (proposed) | Purpose |
|---|---|
| `GRAPHINDEX_PG_DSN` | asyncpg DSN for the backend (also gates live tests) |
| `GRAPHINDEX_PG_SCHEMA` | schema name, default `graphindex` |
| `GRAPHINDEX_EMBEDDING_DIM` | vector column dimension / ANN index creation |
| `GRAPHINDEX_FTS_REGCONFIG` | namespace-prefix → regconfig map (e.g. `legal:* → spanish`, `sym:* → simple`) (D7) |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncpg` | already in use (core) | the backend's only driver (U4, mandatory) |
| `pgvector` (pip) | `>=0.2` | asyncpg codec (`pgvector.asyncpg.register_vector`) |
| PostgreSQL server | `>=15` recommended | `tstzrange`, exclusion constraints, `btree_gist` |
| pgvector server extension | `>=0.8` | KNN + iterative index scans (OQ3 mitigation) |

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — one worktree
  (`.claude/worktrees/feat-520-graphindex-postgres-backend`, branched from
  `dev`), tasks sequential.
- **Why sequential**: Modules 2–8 all touch `persist_postgres.py` /
  `pg_schema.py` / `postgres_store.py`; the dependency chain
  (1 → 2 → {3,4,5} → 6 → 7, 5 → 8, → 9) leaves little safe parallelism, and
  the shared-schema design makes cross-module file contention the norm.
  Modules 5+8 (wiki plane) could in principle run parallel to 3+4 (commit
  protocol/temporal) after Module 2 lands — flag `parallel_group` in
  `/sdd-task` only for those two lanes if a multi-agent run is wanted.
- **Cross-feature dependencies**: none — no in-flight work touches these
  paths (proposal F008); `ast-grep-for-wikitoolkit` (schema v2) is already
  merged on `dev`.

---

## 8. Open Questions

### Resolved (carried from proposal FEAT-520 — do not re-open)

- [x] **Which contract does the backend implement?** — *Resolved in
  proposal (U1)*: both `GraphIndexPersistence` and `BaseWikiStore` over ONE
  shared `graphindex.*` schema. The mapping is designed in §2 of this spec.
- [x] **Where does it ship?** — *Resolved in proposal (U2)*: core package,
  next to the siblings (`parrot/knowledge/graphindex/persist_postgres.py`;
  wiki store at `parrot/knowledge/wiki/postgres_store.py`); asyncpg gated as
  an optional extra.
- [x] **`evidence_ref` semantics?** — *Resolved in proposal (U3)*:
  `(body_ref, byte_offset)` zvec-grep style, defined from day one
  (jsonb column, nullable).
- [x] **PgVectorStore reuse / embeddings co-location?** — *Resolved at
  proposal review gate (U4)*: PgVectorStore NOT reused (SQLAlchemy); asyncpg
  MANDATORY; embeddings in the `graphindex.*` schema (true one-pass);
  re-ranking and RRF machinery patterns reused.
- [x] **Arango migration?** — *Resolved in proposal (U5)*: fresh ingests
  only in v1; no export/import tool.
- [x] **Are the store contract tests backend-parametrized?** (brainstorm
  OQ4) — *Resolved by research*: yes for the wiki plane
  (`test_store.py:29`); graphindex parity bar is
  `test_persist_commit_protocol.py`.

### Unresolved

- [ ] **OQ3 — KNN filtered by graph subset**: spike with a realistic corpus,
  both directions, before freezing `hybrid_retrieve` CTE order — *Owner:
  Module 7, first task*. Mitigations pre-approved: pgvector ≥ 0.8 iterative
  scan; exact scan for depth ≤ 3 hoods; invert CTE order by cardinality.
- [ ] **OQ5 (inherited, legal wiki) — extracting `valid_from` from sources
  that don't state it** — *Owner: legal ingest (Sprint-4 scope, outside this
  spec's modules)*. Interim rule stands and is representable today:
  `valid_from = tx_from`, row marked `derived = true` — never unattributed.
- [ ] **ANN index type default (HNSW vs IVFFlat) and build timing** —
  *Owner: Module 6*, decide with the OQ3 spike data; config-driven either
  way.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-03 | Jesus Lara + Claude (/sdd-spec) | Initial draft from proposal FEAT-520 + brainstorm D1–D8 |
