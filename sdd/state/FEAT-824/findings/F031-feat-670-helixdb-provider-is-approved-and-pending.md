---
id: F031
query_id: Q204
type: wiki_page
intent: "Follow-up: is there an already-approved plan for a different graph engine on the same planes?"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 3500
parent_id: F030
depth: 2
merged_from: [FW-011]
---

# F031 — FEAT-670 "HelixDB graph provider" is approved with 26 pending tasks: it targets the same planes with a different engine and explicitly does NOT retire ArangoDB — a direct conflict with the draft

## Summary

`helixdb-provider.spec.md` (FEAT-670, approved 2026-10-14, target 1.3.0, depends on FEAT-540 v0.5; index: 26 tasks, all `pending`, `completed_at` null) adds a `helixdb` backend to every knowledge plane — wiki, GraphIndex, SDD ledger, schema overlay, ontology graph, plus PageIndex/BookStore projections — by registering implementations in the FEAT-540 registries. HelixDB is Apache-2.0, LPG + native vector + BM25, usable embedded or as a server; the spec already concluded that the **local multi-process workflow must use server mode** (embedded for tests/single-process only). Its non-goals state that HelixDB is an *additional* peer and ArangoDB is not retired. The source draft lists HelixDB among rejected *embedded* engines and picks SurrealDB (BSL 1.1) instead, without mentioning FEAT-670. The proposal must decide: supersede FEAT-670, keep it as a peer, or reuse its plane inventory, migration tool (`wikitoolkit migrate --to <backend>`) and backend-neutral `traversal_spec` design.

## Citations

- path: `sdd/specs/helixdb-provider.spec.md`
  symbol: `header`
  wiki_page_id: file:sdd/specs/helixdb-provider.spec.md
  score: n/a (direct wiki_page)
  excerpt: |
    **Feature ID**: FEAT-670 · **Date**: 2026-10-14 · **Status**: approved · **Target version**: 1.3.0
    **Source brainstorm**: `sdd/proposals/helixdb-provider.brainstorm.md` (accepted 2026-10-14; Option A; 9 resolved questions)
    **Depends on**: **FEAT-540 `graphindex-core-seams` v0.5**
    every HelixDB backend is a **registered implementation** of a FEAT-540 contract (`GraphPersistence` + capabilities,
    `GraphDocumentStore` + `OntologyTraversalStore`, `BaseWikiStore`, `SourceManifestBackend`) plugged in through
    FEAT-540's registries (`register_graph_backend`, `register_ontology_backend`, `register_wiki_backend`,
    `register_source_backend`, `register_query_validator`).

- path: `sdd/specs/helixdb-provider.spec.md`
  symbol: `§1 Goals G4, G8, G10, G11`
  wiki_page_id: file:sdd/specs/helixdb-provider.spec.md
  excerpt: |
    G4  `HelixOntologyGraphStore` with the `OntologyGraphStore` method surface, after the eight raw-AQL call sites
        move behind typed traversal methods.
    G8  The local multi-process workflow (post-commit hook + MCP server + parallel sessions) is served by the
        **server** mode; embedded mode is for tests and single-process tools only.
    G10 Ontology traversal patterns can be declared **backend-neutrally**: `TraversalPattern.traversal_spec`
        (start, hops, conditions, ordering, projection) compiles to AQL on ArangoDB and to the DSL op-tree on HelixDB
        through a per-dialect compiler registry; `query_template` stays the ArangoDB-only escape hatch.
    G11 `wikitoolkit migrate --to <backend>` copies a plane between any two registered wiki backends ... with batching,
        a resumable checkpoint and a verification report.

- path: `sdd/specs/helixdb-provider.spec.md`
  symbol: `§1 Non-Goals`
  wiki_page_id: file:sdd/specs/helixdb-provider.spec.md
  excerpt: |
    - Retiring, deprecating or redirecting away from ArangoDB — HelixDB is an **additional** peer backend;
      `ArangoDBWikiStore`, `GraphIndexPersistence`, `docker/arango` are unchanged (resolved Q8).
    - Full relocation of PageIndex / BookStore into HelixDB ... — projection only.
    - Rewriting the bundled ontology YAML patterns (`ontology/defaults/*.yaml`, nine `query_template` ... [truncated]

- path: `sdd/tasks/index/helixdb-provider.json`
  symbol: `FEAT-670`
  excerpt: |
    feature_id FEAT-670 · completed_at None · tasks: {pending: 26}

## Notes

- Licence angle: FEAT-670 chose HelixDB (Apache 2.0); the draft chooses SurrealDB (BSL 1.1, acknowledged in its §11 risk table) to escape ArangoDB's BUSL-1.1. Replacing one source-available engine with another is a point the proposal must address head-on — FEAT-670 is the already-approved permissive-licence alternative.
- The draft's §1 claim "ningún motor embebido (… HelixDB) admite varios procesos escritores" matches FEAT-670 G8 (server mode for multi-process); it is a reason to run a local server, not a reason to exclude HelixDB server mode.
- Two planes absent from the draft appear in this inventory: the **SDD work ledger** (`LedgerStore(SQLiteWikiStore)`) and the **SQL schema overlay** (`SchemaStore(SQLiteWikiStore)`); both ride on the wiki store contract and are SQLite-only today, so they are unaffected by Arango removal.
- `docker/arango` is named as an existing artefact — Arango removal also covers infra/compose files, not just Python.
- FEAT-670 lists "nine `query_template`" AQL patterns in `ontology/defaults/*.yaml` (sentence truncated in the wiki page) — the concrete set a non-Arango ontology backend must recompile via `traversal_spec`.
- Local `dev` index says all 26 tasks pending; per repo memory a feature branch can be ahead of `dev`.
- [cross-lane: type=git_log, intent=check origin for a feat-FEAT-670-helixdb-provider branch / open PR and whether any HelixDB code (parrot/knowledge/helix/, TraversalPattern.traversal_spec, register_query_validator) already landed on dev]
- [cross-lane: type=grep, intent=does TraversalPattern.traversal_spec or register_query_validator exist in packages/ai-parrot/src/parrot/knowledge/ontology today]
- Citation `sdd/specs/helixdb-provider.spec.md` :: §1 Problem Statement (plane inventory) omitted here — canonical in F028.
