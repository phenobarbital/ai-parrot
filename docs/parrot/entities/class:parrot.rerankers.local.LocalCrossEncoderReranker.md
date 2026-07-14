---
type: Wiki Entity
title: LocalCrossEncoderReranker
id: class:parrot.rerankers.local.LocalCrossEncoderReranker
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-process cross-encoder reranker using HuggingFace models.
relates_to:
- concept: class:parrot.rerankers.abstract.AbstractReranker
  rel: extends
---

# LocalCrossEncoderReranker

Defined in [`parrot.rerankers.local`](../summaries/mod:parrot.rerankers.local.md).

```python
class LocalCrossEncoderReranker(AbstractReranker)
```

In-process cross-encoder reranker using HuggingFace models.

Loads the model eagerly at construction time with optional warmup so that
the first real ``rerank()`` call does not pay cold-start latency.

A process-wide model cache (keyed by ``(model_name, device, precision)``)
ensures that two bots configured with the same reranker share one model
in memory.  A per-device ``ThreadPoolExecutor(max_workers=1)`` serialises
GPU access to prevent OOM under concurrent requests.

Example:
    >>> from parrot.rerankers import LocalCrossEncoderReranker, RerankerConfig
    >>> reranker = LocalCrossEncoderReranker(
    ...     config=RerankerConfig(
    ...         model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
    ...         device="cpu",
    ...         precision="fp32",
    ...     )
    ... )
    >>> results = await reranker.rerank("my query", documents, top_n=5)

## Methods

- `async def rerank(self, query: str, documents: list[SearchResult], top_n: Optional[int]=None) -> list[RerankedDocument]` — Score ``(query, document)`` pairs and return them sorted by relevance.
- `async def cleanup(self) -> None` — Shut down the per-device ThreadPoolExecutor.
