---
id: F022
query_id: Q105
type: read
intent: "Task status of the two specs this proposal overlaps (graphindex-postgres-backend, wikitoolkit-arangodb-backend)"
executed_at: 2026-11-06T13:40:00Z
duration_ms: 1200
parent_id: null
depth: 0
merged_from: [FG-005]
---

# F022 — Both overlapping specs are fully shipped and merged; a third (FEAT-540 graphindex-core-seams) already built the backend registries this proposal needs

## Summary

Per-spec indexes on the working tree: **`graphindex-postgres-backend` = FEAT-520, 10/10 tasks
`done`, `completed_at` 2026-09-03**; **`wikitoolkit-arangodb-backend` = FEAT-400, 7/7 `done`,
`completed_at` 2026-08-01**. A third index not named in the plan is the most relevant one:
**`graphindex-core-seams` = FEAT-540, 34/34 `done`, `completed_at` 2026-10-15**, whose tasks
introduce backend registries and neutral contracts for all three planes (GraphIndex persistence,
wiki store, ontology graph store). `git branch -r --merged origin/dev` confirms
`origin/feat-520-graphindex-postgres-backend`, `origin/feat-400-wikitoolkit-arangodb-backend` and
`origin/feat-FEAT-540-graphindex-core-seams` are all merged; the only related unmerged remote
branch is `origin/feat-255-ontology-rag-kb`. No `surreal*` branch exists. So: Postgres for
GraphIndex **and for the wiki** (`PostgresWikiStore`, TASK-2768) is shipped; ArangoDB for the wiki
is shipped; the ontology store has a contract but only an Arango implementation.

## Citations

- path: `sdd/tasks/index/graphindex-postgres-backend.json`
  symbol: `feature_id`
  excerpt: |
    feature_id=FEAT-520 type=feature base_branch=dev
    created_at=2026-09-03T00:00:00+00:00 completed_at=2026-09-03T13:29:23+00:00
    tasks=10 {'done': 10}  TASK-2764 .. TASK-2773
    TASK-2765 done - PostgresPersistence — parity surface with bitemporal writes
    TASK-2768 done - PostgresWikiStore — BaseWikiStore over the shared schema
    TASK-2770 done - OQ3 spike — KNN under graph filter, CTE order, ANN index choice
    TASK-2771 done - hybrid_retrieve — one-pass SQL (graph + KNN + FTS + RRF) + re-ranking
    TASK-2772 done - Wiki symbol surface (schema v2) on Postgres

- path: `sdd/tasks/index/wikitoolkit-arangodb-backend.json`
  symbol: `feature_id`
  excerpt: |
    feature_id=FEAT-400 type=feature base_branch=dev
    created_at=2026-08-01T00:00:00Z completed_at=2026-08-01T18:15:44+00:00
    tasks=7 {'done': 7}  TASK-2057 .. TASK-2063
    TASK-2057 done - Implement ArangoDBWikiStore
    TASK-2059 done - Extend Factory + Toolkit Wiring for ArangoDB
    TASK-2060 done - SourceCollectionManager ArangoDB Backend
    TASK-2063 done - Integration Tests for ArangoDB Wiki Backend

- path: `sdd/tasks/index/graphindex-core-seams.json`
  symbol: `feature_id`
  excerpt: |
    feature_id=FEAT-540 type=feature base_branch=dev
    created_at=2026-09-15T17:46:21+00:00 completed_at=2026-10-15T23:04:35+00:00
    tasks=34 {'done': 34}  TASK-4300 .. TASK-4333
    TASK-4302 done - graphindex/protocols.py — provider + persistence Protocols, edge_key, errors
    TASK-4319 done - graphindex/backends.py registry, NullPersistence, file_hashes capability, conformance suit
    TASK-4320 done - persist.py → persist_arango.py: ArangoPersistence over GraphDocumentStore
    TASK-4323 done - WikiBackendSpec registry in wiki/store.py; backend-neutral namespace dispatch
    TASK-4325 done - CLI backend choices from the registry; "arangodb" literal audit
    TASK-4326 done - SourceManifestBackend contract; SourceCollectionManager delegates (sqlite/json/arangodb)
    TASK-4327 done - ontology/contracts.py, query-dialect validators, new exceptions
    TASK-4328 done - ArangoOntologyGraphStore implements both contracts with typed traversals
    TASK-4329 done - TraversalPattern.query_templates, ResolvedIntent query/dialect, mixin uses the contract
    TASK-4331 done - parrot_tools legal/procedures/contracts use execute_pattern / explicit Arango store

- branches (`git branch -r --merged origin/dev`, filtered):
  merged: `origin/feat-520-graphindex-postgres-backend`, `origin/feat-400-wikitoolkit-arangodb-backend`,
  `origin/feat-FEAT-540-graphindex-core-seams`, `origin/feat-053-ontological-graph-rag`,
  `origin/feat-465-fix-weak-sha1-arango-store`, `origin/fix/arango-document-key-tilde`,
  `origin/fix/wiki-arangodb-keys-and-bilingual-search`, `origin/fix/ci-feat-540-wiki-regressions`
  not merged (`--no-merged`, pattern graphindex|arango|ontolog|surreal): `origin/feat-255-ontology-rag-kb` only

## Notes

- Paths the FEAT-540 task titles name (to be confirmed by the codebase lane, not verified here):
  `graphindex/protocols.py`, `graphindex/backends.py` (with a "conformance suite"),
  `graphindex/persist_arango.py`, `wiki/store.py` (`WikiBackendSpec`), `ontology/contracts.py`.
  These are the extension points a Postgres ontology store / SurrealDB store would register into;
  the draft's "T3 … suite de contrato" and D7 ("contratos por operaciones semánticas") overlap
  with what FEAT-540 already delivered.
- TASK-4331 says `parrot_tools` legal/procedures/contracts toolkits use `execute_pattern` or an
  **explicit Arango store** — i.e. some tool code is still Arango-bound by construction.
- `origin/feat-255-ontology-rag-kb` is unmerged: `sdd/specs/ontology-rag-kb.spec.md` exists on
  dev, so a spec'd ontology feature has work sitting on a branch that a backend swap could
  conflict with.
- `[cross-lane: type=read, intent=sdd/tasks/index/ontology-rag-kb.json — status of FEAT-255 and whether its unmerged branch touches ontology/graph_store.py]`
- `[cross-lane: type=grep, intent=which parrot_tools legal/procedures/contracts modules construct an explicit Arango store (TASK-4331) — Arango-bound call sites outside the ontology contract]`
- `[cross-lane: type=read, intent=graphindex/backends.py conformance suite — reusable as the draft's shared contract suite]`
