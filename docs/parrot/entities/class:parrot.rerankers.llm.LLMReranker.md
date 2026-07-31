---
type: Wiki Entity
title: LLMReranker
id: class:parrot.rerankers.llm.LLMReranker
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Debug reranker that uses an LLM to score query-passage pairs.
relates_to:
- concept: class:parrot.rerankers.abstract.AbstractReranker
  rel: extends
---

# LLMReranker

Defined in [`parrot.rerankers.llm`](../summaries/mod:parrot.rerankers.llm.md).

```python
class LLMReranker(AbstractReranker)
```

Debug reranker that uses an LLM to score query-passage pairs.

This reranker calls the LLM once per document to obtain a relevance score
in the range ``[0.0, 1.0]``.  Documents are scored concurrently via
``asyncio.gather()``.  Results are sorted in descending order by score.

On any failure (LLM error, parse error), the reranker logs a WARNING and
returns the original ordering with ``rerank_score=float('nan')``.

Args:
    client: Any concrete ``AbstractClient`` subclass (OpenAI, Anthropic, etc.).
    model_name: Optional display name for ``rerank_model`` in the output.
        Defaults to ``"llm-reranker"``.
    **kwargs: Reserved for future extension.

Example:
    >>> reranker = LLMReranker(client=openai_client)
    >>> results = await reranker.rerank("What is ML?", documents, top_n=3)

## Methods

- `async def rerank(self, query: str, documents: list[SearchResult], top_n: Optional[int]=None) -> list[RerankedDocument]` — Score ``(query, document)`` pairs via LLM and return sorted results.
