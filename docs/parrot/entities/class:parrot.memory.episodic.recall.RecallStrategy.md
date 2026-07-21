---
type: Wiki Entity
title: RecallStrategy
id: class:parrot.memory.episodic.recall.RecallStrategy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Protocol for pluggable recall strategies.
---

# RecallStrategy

Defined in [`parrot.memory.episodic.recall`](../summaries/mod:parrot.memory.episodic.recall.md).

```python
class RecallStrategy(Protocol)
```

Protocol for pluggable recall strategies.

Implementations define how to search for similar episodes given a query
and its embedding. The strategy can use vector similarity alone (default)
or fuse multiple signals (e.g., BM25 + semantic).

## Methods

- `async def search(self, query: str, query_embedding: list[float], backend: AbstractEpisodeBackend, namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]` — Search for relevant episodes.
