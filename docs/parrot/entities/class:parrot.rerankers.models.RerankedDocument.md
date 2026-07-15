---
type: Wiki Entity
title: RerankedDocument
id: class:parrot.rerankers.models.RerankedDocument
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A SearchResult enriched with reranker scoring.
---

# RerankedDocument

Defined in [`parrot.rerankers.models`](../summaries/mod:parrot.rerankers.models.md).

```python
class RerankedDocument(BaseModel)
```

A SearchResult enriched with reranker scoring.

The original ``SearchResult`` is preserved via composition (not inheritance)
so that downstream context-building code can extract ``document`` and continue
with the existing pipeline unchanged.

Attributes:
    document: The original retrieval hit from the vector store.
    rerank_score: Raw reranker logit / relevance score (higher = more relevant).
        May be ``float('nan')`` when the reranker failed and returned the
        original ordering as a fallback.
    rerank_rank: 0-based rank after reranking (0 = most relevant).
    original_rank: 0-based rank in the upstream retrieval result (before rerank).
    rerank_model: HuggingFace model ID used for scoring.
    rerank_latency_ms: End-to-end latency for the full batch, in milliseconds.
        Populated by the reranker for telemetry; ``None`` if not measured.
