---
id: F026
query_id: Q206
type: wiki_page
intent: "Key decisions of the wikitoolkit ArangoDB backend spec (what a replacement must preserve)"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 2500
parent_id: null
depth: 0
merged_from: [FW-006]
---

# F026 — FEAT-400 chose ArangoDB for the wiki plane to get a shared, server-hosted wiki with BM25 (ArangoSearch); its contract is `BaseWikiStore` (15 abstract methods) over `wiki_*` collections, default backend stays sqlite

## Summary

`wikitoolkit-arangodb-backend.spec.md` (FEAT-400, approved, 7/7 tasks done, `completed_at` 2026-08-01) added `ArangoDBWikiStore(BaseWikiStore)` in `wiki/arango_store.py`. What ArangoDB was chosen for: (1) shared knowledge graphs across repos/agents on one server, (2) server-hosted wikis that survive across CI/staging/dev without syncing `.db` files, (3) graph traversals + ArangoSearch BM25 richer than SQLite FTS5. Storage: five collections (`wiki_pages`, `wiki_edges`, `wiki_embeddings`, `wiki_sources`, `wiki_meta`) plus an ArangoSearch view in database `wiki_{wiki_name}`; vector search is brute-force `rank_by_cosine()`; credentials come from `ARANGODB_*` env vars via navconfig. Non-goals worth carrying into a replacement: no SQLite→server migration tooling, no multi-tenant isolation inside one database, no commit/audit/revert protocol on the wiki contract, and a generic "remote store" abstraction was explicitly rejected at the time (later reversed by FEAT-540's registry).

## Citations

- path: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
  symbol: `§1 Problem Statement / Goals G1–G5`
  wiki_page_id: file:sdd/specs/wikitoolkit-arangodb-backend.spec.md
  score: n/a (direct wiki_page)
  excerpt: |
    - **Shared knowledge graphs**: multiple repos/agents pointing at the same wiki instance on a centralized ArangoDB server.
    - **Server-hosted wikis**: a production ArangoDB deployment that persists across environments (CI, staging, dev machines).
    - **Graph-native queries**: ArangoDB's graph traversals and ArangoSearch views offer richer querying than SQLite FTS5.
    G1: A new `ArangoDBWikiStore(BaseWikiStore)` that implements all 15 abstract methods via AQL and ArangoSearch views.
    G3: `SourceCollectionManager` stores source metadata in an ArangoDB collection (`wiki_sources`).
    G5: Default backend remains `"sqlite"` — zero config change for existing users.

- path: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
  symbol: `§1 Non-Goals`
  wiki_page_id: file:sdd/specs/wikitoolkit-arangodb-backend.spec.md
  excerpt: |
    - SQLite-to-ArangoDB migration tooling (future feature).
    - Multi-tenant wiki isolation within one ArangoDB database.
    - Native ArangoDB vector index (`APPROX_NEAR`) — use the existing `rank_by_cosine()` brute-force approach initially.
    - Commit/audit/revert protocol for wiki writes (not part of `BaseWikiStore` contract).
    - A generic "remote store" abstraction supporting Postgres/MongoDB — this is ArangoDB-specific. Rejected during proposal.

- path: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
  symbol: `§2 Overview / Integration Points`
  wiki_page_id: file:sdd/specs/wikitoolkit-arangodb-backend.spec.md
  excerpt: |
    Connection credentials come from environment variables following the established `ARANGODB_*` pattern via
    navconfig, never hardcoded in `wiki.json`. The database name is configurable in `wiki.json`, defaulting to
    `wiki_{wiki_name}` for isolation from the ontology database.
    | `SourceCollectionManager` | extends | Add `"arangodb"` backend option |
    | `LLMWikiToolkit.__init__` | modifies | Add wiring for arangodb store + sources |
    | `cli.py` | modifies | Backend option routing for arangodb |
    | `OntologyGraphStore` | reference pattern | Connection + UPSERT patterns |
    | `ArangoDBStore` (embeddings) | reference pattern | ArangoSearch view creation patterns |

- path: `sdd/tasks/index/wikitoolkit-arangodb-backend.json`
  symbol: `FEAT-400`
  excerpt: |
    feature_id FEAT-400 · completed_at 2026-08-01T18:15:44+00:00 · tasks: {done: 7}

## Notes

- Wiki data model in the DB = `pages` (concept_id, node_id, title, category, summary, **body inline**, origin, asserted_by, token_count), `edges` (src, dst, rel, provenance), `embeddings` (one vector per page), `sources` (manifest), `meta`. The draft's KnowledgeStore schema (`bundle → document → section → chunk`, `entity`, `mentions`, `related`, `synth`) is a **chunk-level RAG model**, not this page-level model; mapping one onto the other is undecided in the draft.
- The path `wiki/arango_store.py` is cited from the spec text, not confirmed on disk by this lane.
- The three properties Arango was chosen for (shared server plane, BM25, graph edges) are exactly what the draft claims for SurrealDB; the first two are *also* already served by `PostgresWikiStore` (F025) except true BM25.
- FEAT-540 later moved the `SourceCollectionManager` AQL branch behind a `SourceManifestBackend` contract with `register_source_backend` (F030), so a SurrealDB source manifest is also a registration, not a branch.
- [cross-lane: type=glob, intent=confirm packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py and postgres_store.py exist and list the Arango-specific wiki files (17 files mention arango)]
- Citation `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` :: ArangoDBWikiStore omitted here — canonical in F009.
