---
type: Wiki Entity
title: SemanticOnlyStrategy
id: class:parrot.memory.episodic.recall.SemanticOnlyStrategy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Recall strategy that delegates directly to backend.search_similar().
---

# SemanticOnlyStrategy

Defined in [`parrot.memory.episodic.recall`](../summaries/mod:parrot.memory.episodic.recall.md).

```python
class SemanticOnlyStrategy
```

Recall strategy that delegates directly to backend.search_similar().

This is the default behavior — pure vector similarity search.
Produces identical results to calling backend.search_similar() directly.

## Methods

- `async def search(self, query: str, query_embedding: list[float], backend: AbstractEpisodeBackend, namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]` — Search using pure vector similarity via backend.search_similar().
