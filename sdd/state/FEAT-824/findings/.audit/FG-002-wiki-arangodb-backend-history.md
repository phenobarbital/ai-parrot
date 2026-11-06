---
id: FG-002
query_id: Q102
type: git_log
intent: "When and why the wikitoolkit ArangoDB backend landed"
executed_at: 2026-11-06T13:38:00Z
duration_ms: 700
parent_id: null
depth: 0
---

# FG-002 — wikitoolkit ArangoDB backend: landed 2026-08-01 (FEAT-400), then three months of continuous fixes and feature parity work

## Summary

`git log origin/dev -i --grep=arango -- packages/ai-parrot/src/parrot/knowledge/wiki` returns 25+
commits from 2026-08-01 to 2026-10-15. The backend (`ArangoDBWikiStore`, config models, factory,
`SourceCollectionManager` Arango backend, CLI `--backend`) landed on **2026-08-01** as
`wikitoolkit-arangodb-backend` (FEAT-400). It was made actually usable only on 2026-08-20
("make the ArangoDB backend usable, and searchable in two languages", a second author), and has
since accreted backend-parity obligations: document metadata on source manifests (sqlite + Arango),
federated namespaces, `compare_and_swap_page` (wiki-ADR, FEAT-578), a meta API "for arango and
postgres" (2026-09-28), a mocked Arango lint test, and — in FEAT-540 on 2026-10-15 — a
backend-neutral `SourceManifestBackend` contract. No commit states *why* ArangoDB was chosen;
the log only shows that every wiki feature since August ships for sqlite, Arango and (from
September) Postgres in parallel.

## Citations

- commit: `aa517c6074` — 2026-08-01 — Jesus — `feat(wikitoolkit-arangodb-backend): TASK-2061 — CLI Integration for ArangoDB Backend`
  path: `packages/ai-parrot/src/parrot/knowledge/wiki`
  files: 2 files changed, +92/-10

- commit: `d791f84956` — 2026-08-01 — Jesus — `fix(wikitoolkit-arangodb-backend): code review — real-driver view-creation bug, toolkit sources wiring gap, cross-loop connection reuse`
  path: `packages/ai-parrot/src/parrot/knowledge/wiki`
  files: 4 files changed, +153/-36

- commit: `c51372341d` — 2026-08-20 — Javier León — `fix(wiki): make the ArangoDB backend usable, and searchable in two languages`
  path: `packages/ai-parrot/src/parrot/knowledge/wiki`
  files: 1 file changed, +229/-44

- commit: `4b732e5fa8` — 2026-08-23 — Jesus Lara — `feat(wikitoolkit-ingest-documents): TASK-2355 — persist document metadata on SourceManifestEntry (sqlite + Arango)`
  path: `packages/ai-parrot/src/parrot/knowledge/wiki`
  files: 2 files changed, +162/-46

- commit: `4066e9b144` — 2026-08-23 — Jesus Lara — `sdd: TASK-2362 FederatedWikiStore + namespace resolver`
  path: `packages/ai-parrot/src/parrot/knowledge/wiki`
  files: 2 files changed, +1020

- commit: `715020eeef` — 2026-08-24 — Jesus — `changes in config arango for wiki toolkit`
  path: `packages/ai-parrot/src/parrot/knowledge/wiki`
  files: 4 files changed, +488/-71

- commit: `43ba79e933` — 2026-08-27 — Jesus — `feat(FEAT-465): replace SHA-1 with SHA-256 in arango_store.document_key()`
  path: `packages/ai-parrot/src/parrot/knowledge/wiki`
  symbol: `document_key`
  files: 1 file changed (arango_store, per the subject)

- commit: `edbd5c4645` — 2026-09-19 — Jesus — `feat(wiki-adr): TASK-3483 — compare_and_swap_page on ArangoDBWikiStore`
  path: `packages/ai-parrot/src/parrot/knowledge/wiki`
  symbol: `ArangoDBWikiStore.compare_and_swap_page`
  files: 1 file changed, +81; follow-up `74bdd246b4` (2026-09-20) "ArangoDB CAS AQL syntax, Postgres absent-insert race"

- commit: `cbcbe45644` — 2026-09-28 — revbot — `feat(wikitoolkit-structural-coverage): TASK-3825 — meta API for arango and postgres`
  path: `packages/ai-parrot/src/parrot/knowledge/wiki`
  files: 2 files changed, +48

- commit: `c8a36682ca` — 2026-10-15 — Jesus — `fix(graphindex-core-seams): sync source backends, no per-call asyncio.run, drop monkeypatching`
  path: `packages/ai-parrot/src/parrot/knowledge/wiki`
  files: 3 files changed, +321/-584; sibling `63fb78c8cd` restores `_ARANGO_SOURCES_COLLECTION` used by `sources.py`

## Notes

- The wiki plane already has **three** store implementations in history (sqlite, ArangoDB,
  Postgres — see FG-003/FG-005 for `PostgresWikiStore`, TASK-2768). Removing ArangoDB from the
  wiki is therefore a deletion plus a namespace-data migration, not a from-scratch backend; a
  SurrealDB store would be a fourth implementation of the same `BaseWikiStore` surface.
- Surface a replacement must keep at parity (from commit subjects): `compare_and_swap_page`,
  source-manifest persistence, federated namespace dispatch, the "meta API", bilingual search.
- `[cross-lane: type=grep, intent=enumerate BaseWikiStore abstract methods and which of them PostgresWikiStore implements — decides whether the draft's SurrealDB KnowledgeStore for the wiki is needed at all or Postgres already covers it]`
- `[cross-lane: type=wiki_query, intent=which wiki namespaces in production/local config actually use backend=arangodb (data to migrate)]`
