---
type: Wiki Summary
title: parrot.rerankers.abstract
id: mod:parrot.rerankers.abstract
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for relevance rerankers.
relates_to:
- concept: class:parrot.rerankers.abstract.AbstractReranker
  rel: defines
- concept: mod:parrot.models.stores
  rel: references
- concept: mod:parrot.rerankers.models
  rel: references
---

# `parrot.rerankers.abstract`

Abstract base class for relevance rerankers.

This module defines the ``AbstractReranker`` ABC that all reranker implementations
must subclass. It follows the same async-first lifecycle pattern as ``AbstractClient``
and ``AbstractStore``:

- One required async method: ``rerank()``.
- Two optional lifecycle hooks: ``load()`` and ``cleanup()``.

Example:
    Implementing a custom reranker::

        from parrot.rerankers import AbstractReranker
        from parrot.rerankers.models import RerankedDocument
        from parrot.models.stores import SearchResult

        class MyReranker(AbstractReranker):
            async def rerank(
                self,
                query: str,
                documents: list[SearchResult],
                top_n: int | None = None,
            ) -> list[RerankedDocument]:
                # score and sort documents ...
                return reranked_docs

## Classes

- **`AbstractReranker(ABC)`** — Abstract base class for relevance rerankers.
