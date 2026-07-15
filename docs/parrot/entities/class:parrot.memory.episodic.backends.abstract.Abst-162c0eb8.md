---
type: Wiki Entity
title: AbstractEpisodeBackend
id: class:parrot.memory.episodic.backends.abstract.AbstractEpisodeBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Protocol defining the storage backend interface for episodes.
---

# AbstractEpisodeBackend

Defined in [`parrot.memory.episodic.backends.abstract`](../summaries/mod:parrot.memory.episodic.backends.abstract.md).

```python
class AbstractEpisodeBackend(Protocol)
```

Protocol defining the storage backend interface for episodes.

Implementations must provide methods for storing, searching,
retrieving, and maintaining episodic memory records.

## Methods

- `async def store(self, episode: EpisodicMemory) -> str` — Store an episode. Returns the episode_id.
- `async def search_similar(self, embedding: list[float], namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]` — Search episodes by vector similarity with dimensional filters.
- `async def get_recent(self, namespace_filter: dict[str, Any], limit: int=10, since: datetime | None=None) -> list[EpisodicMemory]` — Get recent episodes by namespace, ordered by created_at DESC.
- `async def get_failures(self, agent_id: str, tenant_id: str='default', limit: int=5) -> list[EpisodicMemory]` — Get recent failure episodes for an agent.
- `async def delete_expired(self) -> int` — Delete episodes that have passed their expires_at timestamp.
- `async def count(self, namespace_filter: dict[str, Any]) -> int` — Count episodes matching a namespace filter.
