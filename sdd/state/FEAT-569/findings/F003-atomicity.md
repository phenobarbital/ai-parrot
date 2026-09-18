---
id: F003
query_id: Q003
type: read
intent: Metadata patches are not atomic review transitions
executed_at: 2026-09-17T21:50:09.640444+00:00
duration_ms: null
parent_id: null
depth: 1
---

# F003 — Metadata patches are not atomic review transitions

## Summary

The protocol only promises a metadata merge. PostgreSQL merges top-level JSONB keys, leaving concurrent replacements of the same fsrs object vulnerable to stale writes. Redis uses read/merge/write without a transaction in this method. FAISS updates process-local objects and saves replacement snapshots. Review deduplication, ordered state application and crash recovery therefore need a stronger contract; append-only logging alone cannot atomically update state.

## Citations

- path: `packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py`
  lines: 106-125
  symbol: `AbstractEpisodeBackend.update_metadata`
  excerpt: |
        async def update_metadata(
            self,
            episode_ids: list[str],
            patch: dict[str, Any],

- path: `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py`
  lines: 492-525
  symbol: `PgVectorBackend.update_metadata`
  excerpt: |
        async def update_metadata(
            self,
            episode_ids: list[str],
            patch: dict[str, Any],

- path: `packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py`
  lines: 544-596
  symbol: `RedisVectorBackend.update_metadata`
  excerpt: |
        async def update_metadata(
            self,
            episode_ids: list[str],
            patch: dict[str, Any],

- path: `packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py`
  lines: 257-315
  symbol: `FAISSBackend.update_metadata / save`
  excerpt: |
        async def update_metadata(
            self,
            episode_ids: list[str],
            patch: dict[str, Any],

## Notes

Read-only inspection at dev HEAD 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c. Proposed changes are inferences, not existing APIs. Range excerpts are locators; the summary uses the inspected surrounding range.
