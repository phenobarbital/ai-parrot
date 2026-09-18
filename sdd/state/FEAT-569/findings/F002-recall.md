---
id: F002
query_id: Q002
type: read
intent: Recall and warnings require separate integration
executed_at: 2026-09-17T21:50:09.640444+00:00
duration_ms: null
parent_id: null
depth: 1
---

# F002 — Recall and warnings require separate integration

## Summary

EpisodicMemoryStore.recall_similar requires an embedding provider and returns an empty list without one. It delegates ranking to the strategy/backend; get_failure_warnings separately fetches recent failures by tenant and agent and re-sorts by importance and timestamp. Updating semantic recall alone will neither preserve final warning ordering nor provide complete namespace isolation in the recent-failure branch.

## Citations

- path: `packages/ai-parrot/src/parrot/memory/episodic/store.py`
  lines: 377-434
  symbol: `EpisodicMemoryStore.recall_similar`
  excerpt: |
        async def recall_similar(
            self,
            query: str,
            namespace: MemoryNamespace,

- path: `packages/ai-parrot/src/parrot/memory/episodic/store.py`
  lines: 436-508
  symbol: `EpisodicMemoryStore.get_failure_warnings`
  excerpt: |
        async def get_failure_warnings(
            self,
            namespace: MemoryNamespace,
            current_query: str | None = None,

- path: `packages/ai-parrot/src/parrot/memory/episodic/models.py`
  lines: 214-271
  symbol: `MemoryNamespace`
  excerpt: |
    class MemoryNamespace(BaseModel):
        """Hierarchical namespace for isolating episodes.

        Supports queries at different granularity levels:

## Notes

Read-only inspection at dev HEAD 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c. Proposed changes are inferences, not existing APIs. Range excerpts are locators; the summary uses the inspected surrounding range.
