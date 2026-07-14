---
type: Wiki Entity
title: AbstractReranker
id: class:parrot.rerankers.abstract.AbstractReranker
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for relevance rerankers.
---

# AbstractReranker

Defined in [`parrot.rerankers.abstract`](../summaries/mod:parrot.rerankers.abstract.md).

```python
class AbstractReranker(ABC)
```

Abstract base class for relevance rerankers.

All reranker implementations must subclass this class and implement the
``rerank()`` method.  The optional ``load()`` and ``cleanup()`` lifecycle
hooks default to no-ops and can be overridden to manage heavy resources
(e.g. GPU memory, model downloads).

Contract: On internal failure, implementations MUST NOT raise from
``rerank()``.  Instead they MUST return the input documents wrapped as
``RerankedDocument`` with ``rerank_score=float('nan')`` and the original
ordering preserved, allowing the caller to apply a safe fallback policy.

## Methods

- `async def rerank(self, query: str, documents: list[SearchResult], top_n: Optional[int]=None) -> list[RerankedDocument]` — Score ``(query, document)`` pairs and return them sorted by relevance.
- `async def load(self) -> None` — Eager model load.
- `async def cleanup(self) -> None` — Release resources (GPU memory, executors, etc.).
