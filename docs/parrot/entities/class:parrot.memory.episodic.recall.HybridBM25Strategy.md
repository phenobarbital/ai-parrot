---
type: Wiki Entity
title: HybridBM25Strategy
id: class:parrot.memory.episodic.recall.HybridBM25Strategy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Recall strategy that fuses BM25 lexical scores with semantic similarity.
---

# HybridBM25Strategy

Defined in [`parrot.memory.episodic.recall`](../summaries/mod:parrot.memory.episodic.recall.md).

```python
class HybridBM25Strategy
```

Recall strategy that fuses BM25 lexical scores with semantic similarity.

Maintains per-namespace in-memory BM25 indexes built lazily on first search.
Fuses scores as: ``bm25_weight * bm25_score + semantic_weight * semantic_score``.
Both score types are normalized to [0.0, 1.0] before fusion.

The BM25 index is rebuilt from all episodes in the namespace via
``backend.get_recent()``. Stale indexes are rebuilt after ``max_index_age_seconds``.

Args:
    bm25_weight: Weight for BM25 lexical score contribution. Default 0.4.
    semantic_weight: Weight for semantic (vector) score contribution. Default 0.6.
    max_episodes_for_index: Maximum episodes to load for BM25 indexing. Default 5000.
    max_index_age_seconds: Rebuild index after this many seconds. Default 3600.

Raises:
    ImportError: If ``bm25s`` package is not installed (raised at first search, not at import).

## Methods

- `def invalidate(self, namespace_filter: dict[str, Any]) -> None` — Invalidate the BM25 index for a given namespace.
- `async def search(self, query: str, query_embedding: list[float], backend: AbstractEpisodeBackend, namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]` — Search using BM25 + semantic score fusion.
