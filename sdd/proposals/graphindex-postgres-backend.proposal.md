---
id: FEAT-520
title: Postgres backend for GraphIndex — native bitemporal plane + one-pass hybrid retrieval
slug: graphindex-postgres-backend
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  file_path: sdd/proposals/claude_brainstorm-graphindex-postgres.md
  fetched_at: 2026-09-03
  summary_oneline: Postgres backend for GraphIndex with native bitemporal plane (tstzrange) and one-pass hybrid retrieval (graph + KNN + BM25 + reranking)
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-520/
created: 2026-09-03
updated: 2026-09-03
---

# FEAT-520 — Postgres backend for GraphIndex: bitemporal plane + one-pass hybrid retrieval

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: sdd/proposals/claude_brainstorm-graphindex-postgres.md`
> **Audit**: [`sdd/state/FEAT-520/`](../state/FEAT-520/)

---

## 0. Origin

The source is an already-mature brainstorm (8 closed decisions D1–D8, draft SQL
schema, 6 open questions). Full text at `sdd/state/FEAT-520/source.md`. Excerpt:

> GraphIndex (usado por LLMwiki y OntoGraph) tiene hoy backends SQLite y
> ArangoDB. Se propone un tercer backend sobre PostgreSQL con dos objetivos que
> los otros dos no pueden cumplir: **temporalidad como propiedad del motor**
> (`tstzrange` + exclusion constraints) y **retrieval híbrido cuádruple en el
> mismo snapshot transaccional** (grafo temporal + KNN pgvector + BM25 +
> re-ranking, las tres primeras patas en un solo roundtrip SQL).

**Initial signals** (extracted, not interpreted):
- Verbs: "se propone", "port", "enchufarse" → new backend, integration-heavy feature
- Named entities: GraphIndex, LLMwiki, OntoGraph, `BaseWikiStore`, pgvector, asyncpg, `tstzrange`, RRF, BOE/CELLAR
- Source marks its own unverified claims with `⚠️ VERIFY` — this research targeted exactly those
- Acceptance criteria provided: no (roadmap of 4 sprints instead)

---

## 1. Synthesis Summary

The request is a third GraphIndex backend on PostgreSQL that makes bitemporal
versioning an engine-enforced property and serves hybrid retrieval in one SQL
roundtrip. Research confirms the target seam is **GraphIndex's own persistence
contract** — `GraphIndexPersistence` (`persist.py`, ArangoDB) mirrored by
`SQLitePersistence` (`persist_sqlite.py`) — which since ~Aug 2026 also includes
the **graph commit protocol** (`apply_update`/`revert_commit` with pre-images);
`BaseWikiStore` (`wiki/store.py`) is a separate contract with its own backends.
Per the Q&A decision (U1), FEAT-520 implements **both contracts over one shared
`graphindex.*` Postgres schema**, in the core package, with **asyncpg mandatory**
(the SQLAlchemy-based `PgVectorStore` is explicitly not reused; embeddings live
in the graphindex schema). Three of the brainstorm's premises were corrected by
evidence: `hybrid_search` already exists on `PgVectorStore` (naming collision to
manage), no BM25-over-Postgres seam exists (the FTS leg is built new; the RRF
and reranker machinery are what gets reused), and the asyncpg invariant holds
for core but not for the store layer. Recommendation: proceed to `/sdd-spec`.

---

## 2. Codebase Findings

> Grounded in `sdd/state/FEAT-520/findings/`. Each entry cites finding IDs.

### 2.1 Localization

| # | Path | Symbol | Role | Evidence |
|---|------|--------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` | `GraphIndexPersistence` | Arango backend whose public API (`persist_graph`, `replace_document_slice`, `load_graph`, `apply_update`/commit protocol) the Postgres backend must mirror | F001 |
| 2 | `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py` | `SQLitePersistence` | Declared mirror pattern; aiosqlite + FTS5/BM25 + `files` staleness table — closest structural template | F001 |
| 3 | `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` | backend factory | Where the third backend registers (today instantiates `SQLitePersistence` or the Arango path) | F001 |
| 4 | `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py` | `UniversalNode`/`UniversalEdge`/`Provenance`/`EdgeKind`/`AssertionMeta`/`GraphUpdate` | Models the SQL schema must represent; validator: `confidence` iff `provenance==INFERRED`; `content_ref` = markdown-on-disk pointer | F006 |
| 5 | `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | `BaseWikiStore`, `WIKI_SCHEMA_SQL`, `SCHEMA_VERSION="2"`, `_MIGRATION_COLUMNS` | The wiki-plane contract (16 abstract methods + non-abstract schema-v2 symbol surface) the shared schema must also serve (U1) | F002 |
| 6 | `packages/ai-parrot-embeddings/src/parrot/stores/postgres.py:1728` | `PgVectorStore.hybrid_search` | EXISTING dense+ColBERT hybrid (SQLAlchemy) — naming collision; NOT reused (U4) | F003 |
| 7 | `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | `HybridPageIndexSearch._rrf_fuse` / `_apply_reranker` | Reusable RRF (k=60) + reranker consumption pattern for D6 steps 2 and 4 | F004, F005 |
| 8 | `packages/ai-parrot/src/parrot/knowledge/graphindex/grounding.py:204` | `ground_claim(claim: str) -> GroundingResult` | Evidence = `stable_edge_id` paths over the in-memory graph; no chunk FK exists — `evidence_ref` is a new field | F006 |
| 9 | `packages/ai-parrot/tests/knowledge/wiki/test_store.py`, `tests/knowledge/graphindex/test_persist_commit_protocol.py` | `store` fixture `params=["sqlite","memory"]` | OQ4: wiki suite is backend-parametrized; graphindex commit-protocol suite is the parity bar | F007 |

### 2.2 Constraints Discovered

- **Commit protocol is part of the contract.** Both existing graphindex
  backends implement `apply_update`/`get_commit`/`list_commits`/`revert_commit`
  with pre-images (`gi_commits`/`gi_commit_items`); `GraphPublisher` depends on
  it for durable agent memory. The Postgres backend must implement it — real
  transactions make this *easier* than Arango's per-tenant-lock serialization.
  *Evidence*: F001, F008
- **`hybrid_search` name is taken.** `PgVectorStore.hybrid_search` (dense +
  ColBERT weighted merge) and `arango.py:801` exist. The graph store's method
  needs deliberate naming/namespacing to avoid confusion.
  *Evidence*: F003
- **No BM25-over-Postgres seam to plug into.** Only FTS artifact today: a GIN
  `to_tsvector('english', …)` index (hardcoded English) at
  `stores/postgres.py:1488`. The D6 FTS leg (with D7's per-namespace
  `regconfig`) is new construction; RRF and reranker patterns are the reuse.
  *Evidence*: F004
- **asyncpg mandatory; PgVectorStore not reused** (user directive at review
  gate). asyncpg precedent in core: `core/hooks/postgres.py`, `eval/sink.py`,
  `retrieval/pin.py`, `ontology/concept_catalog/seed.py`. Embeddings live in
  the `graphindex.*` schema so the graph+KNN+FTS legs share one transaction
  snapshot (true one-pass).
  *Evidence*: F003
- **Wiki schema v2 just landed** (`content_hash`, `symbols` table, symbol
  methods — TASK-2742..2751, merged ~Aug 2026). A wiki-plane view of the shared
  schema must cover the symbol surface or degrade gracefully (Arango precedent:
  the symbol methods are deliberately non-abstract).
  *Evidence*: F002, F008
- **Reranker seam confirmed as assumed**: `AbstractReranker` + `factory.py` +
  `LocalCrossEncoderReranker` (HuggingFace, in ai-parrot-embeddings); copy the
  `_apply_reranker` consumption pattern (builds `SearchResult` docs, falls back
  to fused order on error).
  *Evidence*: F005

### 2.3 Recent History (Relevant)

| Commit | Message | Relevance |
|--------|---------|-----------|
| `b312160ef` | feat(graphindex): ArangoDB implementation of the graph commit protocol | Commit protocol now on both backends — parity bar raised |
| `b0db0f181`…`e95aa73de` | feat(ast-grep-for-wikitoolkit): TASK-2742..2751 — store schema v2, symbols on every backend | Wiki contract recently extended; still settling |
| `5e32c0b78` | fix(graphindex): PageRank as primary centrality | Active maintenance on graphindex, no store-contract impact |

No branch or commit references a Postgres graphindex/wiki backend — greenfield,
no collision. *Evidence*: F008

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`persist_postgres.py`** (core, `parrot/knowledge/graphindex/`) —
  `PostgresPersistence` mirroring the `GraphIndexPersistence` public API
  including the commit protocol, on asyncpg, over schema `graphindex.*` with
  the bitemporal model (D1–D5: `nodes` identity / `node_versions` append-only
  with `tstzrange validity` + exclusion constraint / `edges` with validity).
- **Postgres `BaseWikiStore` implementation** over the SAME schema (U1) — the
  wiki plane reads/writes pages as nodes/node_versions; file location settled
  in the spec.
- **One-pass hybrid retrieval method** on the new store (D6): recursive-CTE
  temporal graph expansion + pgvector KNN + tsvector FTS fused with RRF in SQL,
  cross-encoder re-ranking via the existing `parrot/rerankers` seam. Named to
  avoid collision with `PgVectorStore.hybrid_search` (C2).
- **Temporal API as contract methods** (D5): `as_of(t)`, `history(concept_id)`,
  `diff(concept_id, t1, t2)`; non-temporal backends raise/serve `t=now()`;
  toolkit exposes them as separate mono-purpose tools.
- **`evidence_ref` as `(body_ref, byte_offset)`** (U3), zvec-grep style,
  defined from day one; `provenance`/`derived` columns per D4.

### What Changes

- **`graphindex/factory.py`** — registers the third backend. *Evidence*: F001
- **`tests/knowledge/wiki/test_store.py`** — `store` fixture gains a
  live-DB-gated `postgres` param (Arango precedent). *Evidence*: F007
- **Graphindex commit-protocol/persist test suites** — Postgres variants at
  parity with `test_persist_commit_protocol.py`. *Evidence*: F007
- **`pyproject.toml`** — asyncpg as optional extra for the backend.

### What's Untouched (Non-Goals)

- `PgVectorStore` / `stores/postgres.py` (SQLAlchemy) — not reused, not
  modified (U4, user directive).
- Existing SQLite/Arango backends — no temporal retrofit.
- Arango→Postgres migration tooling — fresh ingests only in v1 (U5).
- BM25 via ParadeDB `pg_search` — `ts_rank_cd` suffices for top-k context
  (source §5 risk table); revisit only if ranking quality demands it.

### Patterns to Follow

- Mirror-API discipline of `persist_sqlite.py` ("Public API mirrors
  GraphIndexPersistence"), including `files`-style staleness tracking.
  *Evidence*: F001
- `_MIGRATION_COLUMNS`-style idempotent, versioned migration (D8).
  *Evidence*: F002
- RRF `Σ 1/(60+rank)` and `_apply_reranker` fallback semantics from
  `HybridPageIndexSearch`. *Evidence*: F004, F005
- `UniversalEdge` validator semantics (confidence iff INFERRED) must survive
  the SQL round-trip. *Evidence*: F006

### Integration Risks

- **Shared-schema dual contract (U1)** is the largest unknown: wiki pages and
  graph nodes have different identity models (`concept_id` vs `node_id`,
  page `category` vs `NodeKind`). Mapping table/views needed; spec must design
  it explicitly. *Evidence*: F001, F002
- **KNN-under-graph-filter performance** (source OQ3): mitigations noted
  (pgvector ≥0.8 iterative scan; exact scan for small hoods); spike stays in
  the roadmap. *Evidence*: F003
- **Dual embedding write paths**: graphindex embeddings historically flow to
  pgvector via the Arango path; the new backend keeps them in-schema. Ingest
  code must route by backend. *Evidence*: F001, F003

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | GraphIndex and LLM-wiki have separate store contracts; "the Postgres backend" had to pick (resolved: both, one schema — U1) | F001, F002 | high | direct read of both contracts and backends |
| C2 | `hybrid_search` already exists on `PgVectorStore` (dense+ColBERT, SQLAlchemy) | F003 | high | signature read at `postgres.py:1728` |
| C3 | No BM25-over-Postgres exists; FTS leg is built new, RRF/reranker are the reuse | F004 | high | exhaustive grep for FTS primitives |
| C4 | Reranker seam exactly as the brainstorm assumed | F005 | high | factory + impl + consumption pattern verified |
| C5 | `ground_claim` cites stable edge-id paths; no chunk FK anywhere → `evidence_ref` is new (resolved: `(body_ref, offset)` — U3) | F006 | high | direct read of `grounding.py` + schema models |
| C6 | asyncpg invariant holds for core, not the store layer; backend cannot reuse PgVectorStore machinery (resolved: asyncpg mandatory — U4) | F003 | medium→resolved | import inspection; user directive closes it |
| C7 | Wiki store suite is backend-parametrized; Postgres param slots in live-DB-gated | F007 | high | fixture read |
| C8 | Backend must implement the graph commit protocol for parity | F001, F008 | high | both backends implement it; GraphPublisher depends on it |
| C9 | No temporal support and no in-flight Postgres work — greenfield | F002, F006, F008 | medium | negative evidence (greps + git log, 8-week window) |

Distribution: **7** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Which contract does the backend implement?** — *Resolved*: Both
  contracts over ONE shared `graphindex.*` schema (GraphIndexPersistence incl.
  commit protocol AND BaseWikiStore). *Resolves claims*: C1
- [x] **U2 — Where does it ship?** — *Resolved*: Core package, next to the
  siblings (`parrot/knowledge/graphindex/persist_postgres.py`); asyncpg as
  optional extra. *Resolves claims*: C6
- [x] **U3 — `evidence_ref` semantics?** — *Resolved*: `(body_ref,
  byte_offset)` zvec-grep style, defined from day one. *Resolves claims*: C5
- [x] **U4 — Embeddings co-location / PgVectorStore reuse?** — *Resolved* (at
  review gate): PgVectorStore NOT reused (SQLAlchemy); asyncpg MANDATORY;
  embeddings in the `graphindex.*` schema (true one-pass); re-ranking and
  BM25/RRF machinery reused. *Resolves claims*: C2, C6
- [x] **U5 — Arango migration?** — *Resolved*: fresh ingests only in v1.

### Unresolved (defer to spec / implementation)

- [ ] **Wiki-page ↔ graph-node mapping on the shared schema** — *Owner*: spec.
  *Blocks claims*: — (new scope from U1). How `WikiPageRecord`
  (concept_id/category/body) projects onto `nodes`/`node_versions`, and where
  the symbol surface (schema v2) lands.
- [ ] **OQ3 (KNN filtered by graph subset) spike** — *Owner*: Sprint 2/3, with
  a realistic BOE corpus, both directions (graph→semantic, semantic→graph).
- [ ] **OQ5 (heredada) — `valid_from` extraction** from sources that don't
  state it; interim rule stands: `valid_from = tx_from` marked `derived=true`.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-520`** — *Rationale*: localization is high-confidence, the
source already carries closed decisions D1–D8, and all five proposal-blocking
unknowns are resolved. The spec's main new design work is the U1 shared-schema
dual-contract mapping; everything else is encoding corrected premises (FTS leg
built new, commit-protocol parity, asyncpg-only, `evidence_ref` shape).

### Alternatives

- **`/sdd-brainstorm FEAT-520`** — only if the U1 shared-schema decision
  deserves an options analysis before speccing (it is the one structural
  choice research flagged as larger than the source scoped).
- **Manual review** — not indicated; research completed within budget.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-520/state.json` |
| Source (raw) | `sdd/state/FEAT-520/source.md` |
| Research plan | `sdd/state/FEAT-520/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-520/findings/F001-*.md` … `F008-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-520/synthesis.json` |

**Budget consumed** (profile: default):
- Files read: 5 / 40 · Grep calls: 9 / 25 · Git calls: 2 / 10 · Wiki calls: 7 (free)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (source is a
decision-bearing design document with explicit `⚠️ VERIFY` markers).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jlara@trocglobal.com |
