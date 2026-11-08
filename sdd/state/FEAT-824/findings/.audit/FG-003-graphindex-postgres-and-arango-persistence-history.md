---
id: FG-003
query_id: Q103
type: git_log
intent: "State of the GraphIndex Postgres backend work"
executed_at: 2026-11-06T13:38:30Z
duration_ms: 700
parent_id: null
depth: 0
---

# FG-003 — GraphIndex already has a shipped Postgres backend (2026-09-03) next to the ArangoDB one; FEAT-540 put both behind a registry

## Summary

`git log origin/dev -i -E --grep="postgres|arango" -- packages/ai-parrot/src/parrot/knowledge/graphindex`
shows three stages. **2026-05-19**: the original persistence layer was "ArangoDB + pgvector"
(TASK-1260); **2026-08-16**: an ArangoDB implementation of the graph commit protocol.
**2026-09-03 (`graphindex-postgres-backend`, FEAT-520)**: a complete Postgres backend in ten tasks
— `pg_schema.py` (DDL, versioned migration, asyncpg pool), `PostgresPersistence` "parity surface",
the commit protocol on real transactions, a temporal plane (`as_of`/`history`/`diff`), in-schema
embeddings + KNN, and `hybrid_retrieve` as one-pass SQL (graph + KNN + FTS + RRF) with rerank.
**2026-10-15 (FEAT-540)**: `persist.py` renamed to `persist_arango.py` (`ArangoPersistence`) and
Postgres settings made lazy, so ArangoDB is now one registered backend, not the default code path.
Consequence for this proposal: a hybrid graph + vector + FTS + RRF retrieval over plain RDS
Postgres (no AGE) already exists in the repository and was merged two months ago.

## Citations

- commit: `fde8ed0431` — 2026-05-19 — Jesus — `feat(graphindex): TASK-1260 — Persistence Layer (ArangoDB + pgvector)`
  path: `packages/ai-parrot/src/parrot/knowledge/graphindex`
  files: 1 file changed, +277

- commit: `b312160efa` — 2026-08-16 — Claude — `feat(graphindex): ArangoDB implementation of the graph commit protocol`
  path: `packages/ai-parrot/src/parrot/knowledge/graphindex`
  files: 2 files changed, +689/-6

- commit: `edcbb26dd1` — 2026-09-03 — Jesus — `feat(graphindex-postgres-backend): TASK-2764 — pg_schema.py DDL, migration, pool`
  path: `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py`
  files: 1 file changed, +349

- commit: `d1e3db1e0d` — 2026-09-03 — Jesus — `feat(graphindex-postgres-backend): TASK-2765 — PostgresPersistence parity surface`
  path: `packages/ai-parrot/src/parrot/knowledge/graphindex`
  symbol: `PostgresPersistence`
  files: 1 file changed, +571

- commit: `89b7e12db4` — 2026-09-03 — Jesus — `feat(graphindex-postgres-backend): TASK-2766 — commit protocol on real transactions`
  path: `packages/ai-parrot/src/parrot/knowledge/graphindex`
  files: 1 file changed, +465

- commit: `f6613544f3` — 2026-09-03 — Jesus — `feat(graphindex-postgres-backend): TASK-2767 — temporal plane (as_of/history/diff)`
  path: `packages/ai-parrot/src/parrot/knowledge/graphindex`
  files: 1 file changed, +206

- commit: `77e9ce6561` — 2026-09-03 — Jesus — `feat(graphindex-postgres-backend): TASK-2769 — in-schema embeddings + KNN path`
  path: `packages/ai-parrot/src/parrot/knowledge/graphindex`
  files: 2 files changed, +140

- commit: `a27df8ac7c` — 2026-09-03 — Jesus — `feat(graphindex-postgres-backend): TASK-2771 — hybrid_retrieve one-pass SQL + rerank`
  path: `packages/ai-parrot/src/parrot/knowledge/graphindex`
  symbol: `hybrid_retrieve`
  files: 1 file changed, +360

- commit: `7017b953d6` — 2026-09-03 — Jesus — `feat(graphindex-postgres-backend): TASK-2773 — factory wiring, temporal toolkit tools, docs`
  path: `packages/ai-parrot/src/parrot/knowledge/graphindex`
  files: 1 file changed, +37/-7

- commit: `4a2944dcf2` — 2026-10-15 — Jesus — `feat(graphindex-core-seams): TASK-4320 — persist.py → persist_arango.py (ArangoPersistence)`
  path: `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_arango.py`
  symbol: `ArangoPersistence`
  files: 4 files changed, +92/-62; sibling `828a867c2c` "TASK-4312 — pg_schema import-clean, lazy Postgres settings"

## Notes

- The draft (§0, "Fuera de alcance") says GraphIndex L0 "sigue en SQLite per-repo local + tablas
  Postgres centrales, spec aparte". History shows the Postgres side is **not** a future spec: it
  shipped as FEAT-520 with a temporal plane and hybrid retrieval. The draft's D1 rationale
  ("el router necesita JOINs, trgm y pgvector, no traversals") is consistent with that precedent.
- No commit in this path mentions an L1 "synth" cache; where L1 summaries are persisted today is
  not answerable from the log.
- `[cross-lane: type=grep, intent=locate the L1 synthesis/summary cache in knowledge/graphindex (the draft moves it to a Surreal `synth` table) and which backend stores it today]`
- `[cross-lane: type=read, intent=graphindex/pg_schema.py — reuse candidate for the ontology schema's pool, migration runner and pgvector/FTS conventions]`
