---
type: Wiki Entity
title: GraphExpandedRetriever
id: class:parrot.knowledge.graphindex.retriever.GraphExpandedRetriever
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 4-phase graph-expanded retrieval pipeline.
---

# GraphExpandedRetriever

Defined in [`parrot.knowledge.graphindex.retriever`](../summaries/mod:parrot.knowledge.graphindex.retriever.md).

```python
class GraphExpandedRetriever
```

4-phase graph-expanded retrieval pipeline.

Composes existing search, signal-relevance, and community-detection
components — never subclasses them.  At least one of ``hybrid_search``
or ``embedder`` must be provided; both ``None`` raises ``ValueError``.

Args:
    graph: Assembled ``rustworkx.PyDiGraph`` with node payloads.
    nodes: Full list of ``UniversalNode`` instances mirroring graph.
    embedder: Optional ``GraphIndexEmbedder`` for FAISS seed search.
    hybrid_search: Optional ``HybridPageIndexSearch`` for PageIndex seed
        search.  Preferred over ``embedder`` when both are provided.
    signal_config: Optional ``SignalRelevanceConfig`` forwarded to
        ``relevance_neighborhood()``.
    communities: Optional ``CommunitiesResult`` for Phase 3 annotation.

## Methods

- `async def search(self, query: str, seed_top_k: int=10, expansion: Optional[ExpansionConfig]=None, budget: Optional[BudgetConfig]=None) -> GraphRetrievalResult` — Run the full 4-phase retrieval pipeline.
