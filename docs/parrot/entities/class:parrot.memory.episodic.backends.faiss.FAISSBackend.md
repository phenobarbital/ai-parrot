---
type: Wiki Entity
title: FAISSBackend
id: class:parrot.memory.episodic.backends.faiss.FAISSBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: FAISS-based backend for local development without PostgreSQL.
---

# FAISSBackend

Defined in [`parrot.memory.episodic.backends.faiss`](../summaries/mod:parrot.memory.episodic.backends.faiss.md).

```python
class FAISSBackend
```

FAISS-based backend for local development without PostgreSQL.

Uses an in-memory FAISS IndexFlatIP (inner product on L2-normalized
vectors = cosine similarity) with optional disk persistence.

Args:
    dimension: Embedding vector dimension.
    persistence_path: Directory for saving index and episodes to disk.
        If None, runs purely in-memory.
    max_episodes: Maximum number of episodes to keep. When exceeded,
        the oldest episodes are removed.
    auto_save_interval: Save to disk every N store() calls.
        Only applies when persistence_path is set.

## Methods

- `async def configure(self) -> None` — Load persisted data if available.
- `async def close(self) -> None` — Save to disk if persistence is enabled.
- `async def store(self, episode: EpisodicMemory) -> str` — Store an episode in the FAISS index and dict.
- `async def search_similar(self, embedding: list[float], namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]` — Search by vector similarity with post-search namespace filtering.
- `async def get_recent(self, namespace_filter: dict[str, Any], limit: int=10, since: datetime | None=None) -> list[EpisodicMemory]` — Get recent episodes matching the namespace filter.
- `async def get_failures(self, agent_id: str, tenant_id: str='default', limit: int=5) -> list[EpisodicMemory]` — Get recent failure episodes for an agent.
- `async def delete_expired(self) -> int` — Delete episodes past their expires_at timestamp.
- `async def count(self, namespace_filter: dict[str, Any]) -> int` — Count episodes matching a namespace filter.
- `async def save(self) -> None` — Save FAISS index and episodes to disk.
- `async def load(self) -> None` — Load FAISS index and episodes from disk.
