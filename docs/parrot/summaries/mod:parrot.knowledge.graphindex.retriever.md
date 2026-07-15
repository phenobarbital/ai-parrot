---
type: Wiki Summary
title: parrot.knowledge.graphindex.retriever
id: mod:parrot.knowledge.graphindex.retriever
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Graph-Expanded Retrieval Pipeline.
relates_to:
- concept: class:parrot.knowledge.graphindex.retriever.BudgetConfig
  rel: defines
- concept: class:parrot.knowledge.graphindex.retriever.ExpansionConfig
  rel: defines
- concept: class:parrot.knowledge.graphindex.retriever.GraphExpandedRetriever
  rel: defines
- concept: class:parrot.knowledge.graphindex.retriever.GraphRetrievalResult
  rel: defines
- concept: class:parrot.knowledge.graphindex.retriever.ScoredNode
  rel: defines
- concept: mod:parrot.knowledge.graphindex.communities
  rel: references
- concept: mod:parrot.knowledge.graphindex.embed
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.knowledge.graphindex.signals
  rel: references
- concept: mod:parrot.knowledge.pageindex.hybrid_search
  rel: references
---

# `parrot.knowledge.graphindex.retriever`

Graph-Expanded Retrieval Pipeline.

Orchestrates a 4-phase retrieval pipeline over the assembled GraphIndex:

  Phase 1 — Seed Search:
    Selects initial candidate nodes via HybridPageIndexSearch (PageIndex path)
    or GraphIndexEmbedder.search_similar() (FAISS path). Scores normalised to
    ``[0, 1]``.

  Phase 2 — Graph Expansion:
    Starting from seed nodes, traverses the graph N hops outward using
    ``relevance_neighborhood()``.  Scores decay exponentially per hop:
    ``combined = parent_score * decay_base^hop * signal.combined``.  Nodes are
    deduplicated by ``node_id``, keeping the highest combined score.

  Phase 3 — Community Context:
    Annotates each expanded node with ``community_id`` and ``community_cohesion``
    from an optional ``CommunitiesResult``.  When ``CommunitiesResult`` is ``None``
    this phase is a no-op.

  Phase 4 — Result Assembly:
    Sorts nodes by ``combined_score`` (descending), applies a token budget, and
    returns a ``GraphRetrievalResult`` with decomposed scores and metadata.

## Classes

- **`ExpansionConfig(BaseModel)`** — Configuration for the graph expansion phase (Phase 2).
- **`BudgetConfig(BaseModel)`** — Token budget for Phase 4 result assembly.
- **`ScoredNode(BaseModel)`** — A retrieval candidate with decomposed scores.
- **`GraphRetrievalResult(BaseModel)`** — Complete result of a graph-expanded retrieval query.
- **`GraphExpandedRetriever`** — 4-phase graph-expanded retrieval pipeline.
