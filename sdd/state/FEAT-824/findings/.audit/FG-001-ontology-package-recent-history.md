---
id: FG-001
query_id: Q101
type: git_log
intent: "Recent activity on the ontology package"
executed_at: 2026-11-06T13:36:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FG-001 — Ontology package: 26 commits in 120 days, dominated by the FEAT-540 backend-seam refactor

## Summary

`git log origin/dev --since="120 days ago" -- packages/ai-parrot/src/parrot/knowledge/ontology`
returns 26 commits (2026-08-23 → 2026-10-15), single author. Three themes: (1) **2026-10-15,
`graphindex-core-seams` (FEAT-540)** — 13 commits that introduce `ontology/contracts.py`, rename the
store to `ArangoOntologyGraphStore`, add *typed traversals*, add `TraversalPattern.query_templates`
with a query **dialect** on `ResolvedIntent`, and remove the `OntologyGraphStore` /
`execute_traversal` aliases; (2) **2026-08-23 → 2026-09-25** — domain ontologies added as **YAML**
files under `ontology/defaults/domains/` (`legal`, `contracts`, `procedures`), i.e. the ontology
source format in the repository is YAML, not Turtle; (3) **2026-08-27** — *declarative ArangoSearch
views in the ontology schema* (an Arango-specific concept living in `schema.py`/`merger.py`).
The package has been quiet since 2026-10-15 (no commit in the last 3 weeks).

## Citations

- commit: `bf86780d88` — 2026-10-15 — Jesus — `feat(graphindex-core-seams): TASK-4327 — engine-committed coder deliverable`
  path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  files: `ontology/contracts.py` (+205, new file), `ontology/exceptions.py` (+14), `ontology/validators.py` (+46)

- commit: `3ae3dc2820` — 2026-10-15 — Jesus — `feat(graphindex-core-seams): TASK-4328 — ArangoOntologyGraphStore typed traversals`
  path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  files: `ontology/graph_store.py` (+222/-5), `ontology/__init__.py` (+2)

- commit: `5097106625` — 2026-10-15 — Jesus — `feat(graphindex-core-seams): TASK-4329 — query_templates, ResolvedIntent query/dialect, mixin on contract`
  path: `packages/ai-parrot/src/parrot/knowledge/ontology/intent.py`
  files: `ontology/intent.py` (+45), `ontology/mixin.py` (+67), `ontology/schema.py` (+12)

- commit: `d18f42efd1` — 2026-10-15 — Jesus — `feat(graphindex-core-seams): TASK-4330 — engine-committed coder deliverable`
  path: `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py`
  files: `ontology/authorization.py` (128 changed), `ontology/entity_resolver.py` (115 changed)
  note: index title for TASK-4330 is "AuthorizationChecker and EntityResolver call typed traversals" (see FG-005)

- commit: `71ba293198` — 2026-10-15 — Jesus — `feat(graphindex-core-seams): TASK-4332 — remove OntologyGraphStore/execute_traversal aliases`
  path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  files: `ontology/__init__.py`, `ontology/concept_catalog/reconcile.py`, `ontology/concept_catalog/worker.py`, `ontology/contracts.py`, `ontology/graph_store.py`, `ontology/refresh.py`

- commit: `001f34a3f7` — 2026-10-15 — Jesus — `fix(graphindex-core-seams): forward graph dialect to intent resolver, alias legacy aql key, name field in key_field error`
  path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  files: `ontology/graph_store.py` (+15/-3), `ontology/intent.py` (+10), `ontology/mixin.py` (+6)

- commit: `8b0e889f03` — 2026-09-25 — Jesus — `feat(training-agent): TASK-3701 — procedures.ontology.yaml + manuals/domain.py tenant manager`
  path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/procedures.ontology.yaml`
  files: `ontology/defaults/domains/procedures.ontology.yaml` (+685, new)

- commit: `eb47456bce` — 2026-09-09 — Jesus — `feat(contracts-card-ontology): TASK-3036 — contracts ontology vocabulary and allowlisted patterns`
  path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml`
  files: `ontology/defaults/domains/contracts.ontology.yaml` (+827, new)

- commit: `e5f23ec002` — 2026-08-27 — Jesus Lara — `feat(legal-librarian-answer-layer): TASK-2493 — declarative ArangoSearch views in the ontology schema`
  path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  files: `ontology/graph_store.py` (+109), `ontology/merger.py` (+49), `ontology/schema.py` (+57)

- commit: `6478ec5fd3` — 2026-08-23 — Jesus Lara — `feat(legal-norms-graph-boe): TASK-2370 — legal.ontology.yaml entities and relations`
  path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml`
  files: `ontology/defaults/domains/legal.ontology.yaml` (+100, new); follow-ups `fac5e3f0bb` (TASK-2371 `article_in_force` declarative TraversalPattern) and `c8fa31da67` (TASK-2494 legal ontology v1.1 view, `search_articles` pattern)

## Notes

- The commit subject "alias legacy aql key" (`001f34a3f7`) plus "query_templates … query/dialect"
  (`5097106625`) indicates the YAML ontologies carry per-dialect query text (AQL today) inside
  `TraversalPattern`; a new backend needs templates in its own dialect or a dialect-free operation.
- `[cross-lane: type=read, intent=confirm in ontology/schema.py how TraversalPattern.query_templates keys dialects and whether the three domain YAMLs (legal, contracts, procedures) ship only an AQL template]`
- `[cross-lane: type=grep, intent=ArangoSearch view declarations in ontology/schema.py + merger.py — an Arango-only schema concept that a Postgres/Surreal backend must map (FTS/BM25 index) or drop]`
