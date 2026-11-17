---
id: F025
query_id: Q205
type: wiki_page
intent: "Key decisions and non-goals of the GraphIndex Postgres backend spec"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 2500
parent_id: null
depth: 0
merged_from: [FW-005]
---

# F025 — FEAT-520 already put a bitemporal, append-only graph + wiki plane on PostgreSQL (`graphindex.*`), with pgvector + FTS + RRF in SQL, asyncpg only, and no Arango migration

## Summary

`graphindex-postgres-backend.spec.md` (FEAT-520, approved, 10/10 tasks done) defines one Postgres schema, `graphindex.*`, serving two contracts: `PostgresPersistence` (GraphIndex plane, including the commit protocol and a temporal API `as_of` / `history` / `diff` plus `hybrid_retrieve`) and `PostgresWikiStore(BaseWikiStore)` wired as `backend == "postgres"`. Versioning is bitemporal and append-only, enforced by `tstzrange` + an exclusion constraint; hybrid retrieval fuses graph expansion, pgvector KNN and FTS with RRF in a single SQL statement, re-ranked through `parrot/rerankers`. Binding choices: **asyncpg mandatory, no SQLAlchemy, do not reuse `PgVectorStore`, `ts_rank_cd` instead of true BM25**, and "fresh ingests only — Arango tenants stay on Arango". The draft's OntologyStore (append-only, `since_version/until_version`, pgvector, `asyncpg vía asyncdb`) overlaps this design in mechanism but uses a different versioning model (integer versions vs `tstzrange` validity) and a different schema (`ontology.*`).

## Citations

- path: `sdd/specs/graphindex-postgres-backend.spec.md`
  symbol: `§1 Goals G1–G7`
  wiki_page_id: file:sdd/specs/graphindex-postgres-backend.spec.md
  score: n/a (direct wiki_page)
  excerpt: |
    G1. A third GraphIndex persistence backend on PostgreSQL (asyncpg, **mandatory** — resolved U4) at functional
        parity with `SQLitePersistence` / `GraphIndexPersistence`, **including the graph commit protocol**.
    G2. A `BaseWikiStore` implementation over the **same** `graphindex.*` schema (resolved U1).
    G3. Bitemporal, append-only versioning enforced by the engine (D1, D2) with zero cost on the current-time read path (D3).
    G4. Temporal API as deterministic contract methods: `as_of(t)`, `history(concept_id)`, `diff(concept_id, t1, t2)` (D5).
    G5. One-pass hybrid retrieval (`hybrid_retrieve` ...) with graph/KNN/FTS legs in one SQL statement, RRF fusion in SQL,
        re-ranking through the existing `parrot/rerankers` seam (D6).
    G6. Language-parametric FTS: per-node `lang`, tsvector populated at upsert time, regconfig-per-namespace (D7).
    G7. Evidence and provenance on edges: `provenance`, `derived`, and `evidence_ref` (D4, resolved U3).

- path: `sdd/specs/graphindex-postgres-backend.spec.md`
  symbol: `§1 Non-Goals`
  wiki_page_id: file:sdd/specs/graphindex-postgres-backend.spec.md
  excerpt: |
    - Migrating existing Arango graphs — **fresh ingests only in v1** (resolved U5); Arango tenants stay on Arango.
    - Reusing or modifying `PgVectorStore` (`ai-parrot-embeddings` `stores/postgres.py`) — it is SQLAlchemy-based
      and explicitly excluded (resolved U4). Embeddings for this backend live in the `graphindex.*` schema.
    - Temporal retrofit of the SQLite/Arango backends — ... temporal methods raise `NotImplementedError` (D5).
    - ParadeDB `pg_search` / true BM25 in Postgres — `ts_rank_cd` suffices for top-k context assembly.
    - SQLAlchemy anywhere in this backend (D8).

- path: `sdd/specs/graphindex-postgres-backend.spec.md`
  symbol: `§2 Overview`
  wiki_page_id: file:sdd/specs/graphindex-postgres-backend.spec.md
  excerpt: |
    - **`PostgresPersistence`** (`parrot/knowledge/graphindex/persist_postgres.py`) mirrors the
      `GraphIndexPersistence` public API ... Where Arango serializes writers with a per-tenant `asyncio.Lock`
      and SQLite with WAL, Postgres uses real transactions.
    - **`PostgresWikiStore(BaseWikiStore)`** (`parrot/knowledge/wiki/postgres_store.py`) implements the wiki
      retrieval plane over the same tables, wired into `create_wiki_store` via `backend == "postgres"`.
    Writes are **append-only** (D2): a correction closes the previous version's `validity` range and inserts a
    new row in the same transaction; content is never UPDATEd.

- path: `sdd/specs/graphindex-postgres-backend.spec.md`
  symbol: `§2 Component Diagram / Integration Points`
  wiki_page_id: file:sdd/specs/graphindex-postgres-backend.spec.md
  excerpt: |
    graphindex.* (one Postgres schema): nodes ── node_versions (bitemporal, EXCLUDE) · edges (validity, evidence_ref)
    · embeddings (pgvector, per version) · symbols · files · commits · commit_items  — asyncpg pool (pg_base)
    | navconfig | config | DSN + regconfig-per-namespace mapping (declarative, D7) |
    | `tests/knowledge/wiki/test_store.py` fixture | extends | `postgres` param, live-DB-gated by env (Arango precedent) |

## Notes

- Spec header: "Feature ID: FEAT-520 … Status: approved … Source brainstorm: `sdd/proposals/claude_brainstorm-graphindex-postgres.md` (decisions D1–D8)". Index: `completed_at 2026-09-03`, 10 done.
- Constraints a new Postgres OntologyStore inherits if it wants to be coherent with the existing Postgres plane: asyncpg (not SQLAlchemy, not `PgVectorStore`), a navconfig DSN in the style of `GRAPHINDEX_PG_DSN`, pgvector in the same database, append-only versioning. The draft's "asyncpg vía asyncdb" wording conflicts with FEAT-520's "asyncpg mandatory" only if asyncdb's pg driver is not asyncpg — the codebase lane should check how `pg_base` builds its pool.
- The draft assumes **Apache AGE unavailable on RDS**; FEAT-520 never used AGE either (relational edges + recursive expansion), so D1 of the draft is consistent with the shipped design.
- The draft rejects Postgres FTS for the knowledge store in favour of "BM25 real" (SurrealDB). FEAT-520 explicitly judged `ts_rank_cd` sufficient and deferred true BM25 "only on measured ranking-quality problems" — a prior decision the proposal reverses and should justify.
- [cross-lane: type=read, intent=check graphindex/pg_schema.py and pg_base for the DSN setting name, pool construction and extension list (vector, pg_trgm?) to reuse for an ontology.* schema]
- Citation `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` :: create_wiki_store omitted here — canonical in F009.
