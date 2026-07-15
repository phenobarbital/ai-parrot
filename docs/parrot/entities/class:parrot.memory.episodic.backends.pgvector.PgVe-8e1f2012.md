---
type: Wiki Entity
title: PgVectorBackend
id: class:parrot.memory.episodic.backends.pgvector.PgVectorBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: PostgreSQL + pgvector backend for episodic memory.
---

# PgVectorBackend

Defined in [`parrot.memory.episodic.backends.pgvector`](../summaries/mod:parrot.memory.episodic.backends.pgvector.md).

```python
class PgVectorBackend
```

PostgreSQL + pgvector backend for episodic memory.

Uses asyncpg connection pool for async access. Auto-creates schema,
table, and indexes on configure(). Similarity search uses cosine
distance with dimensional WHERE filters.

Args:
    dsn: PostgreSQL connection string.
    schema: PostgreSQL schema name.
    table: Table name within the schema.
    pool_size: Connection pool size.

## Methods

- `async def configure(self) -> None` — Create connection pool, schema, table, and indexes.
- `async def close(self) -> None` — Close the connection pool.
- `async def store(self, episode: EpisodicMemory) -> str` — Store an episode. Returns episode_id.
- `async def search_similar(self, embedding: list[float], namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]` — Search episodes by cosine similarity with dimensional filters.
- `async def get_recent(self, namespace_filter: dict[str, Any], limit: int=10, since: datetime | None=None) -> list[EpisodicMemory]` — Get recent episodes ordered by created_at DESC.
- `async def get_failures(self, agent_id: str, tenant_id: str='default', limit: int=5) -> list[EpisodicMemory]` — Get recent failure episodes for an agent.
- `async def delete_expired(self) -> int` — Delete episodes past their expires_at. Returns count deleted.
- `async def count(self, namespace_filter: dict[str, Any]) -> int` — Count episodes matching a namespace filter.
- `async def search_hybrid(self, embedding: list[float], query_text: str, namespace_filter: dict[str, Any], top_k: int=5, semantic_weight: float=0.6, text_weight: float=0.4, score_threshold: float=0.1) -> list[EpisodeSearchResult]` — Search episodes using tsvector full-text + cosine vector fusion.
