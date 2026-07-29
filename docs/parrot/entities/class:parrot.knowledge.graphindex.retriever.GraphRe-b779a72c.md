---
type: Wiki Entity
title: GraphRetrievalResult
id: class:parrot.knowledge.graphindex.retriever.GraphRetrievalResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Complete result of a graph-expanded retrieval query.
---

# GraphRetrievalResult

Defined in [`parrot.knowledge.graphindex.retriever`](../summaries/mod:parrot.knowledge.graphindex.retriever.md).

```python
class GraphRetrievalResult(BaseModel)
```

Complete result of a graph-expanded retrieval query.

Args:
    query: The original query string passed to ``search()``.
    nodes: Ranked list of candidate nodes, sorted by ``combined_score``
        descending.
    total_candidates: Total nodes considered before budget truncation.
    nodes_expanded: Number of nodes added during Phase 2 (does not
        include seeds).
    communities_touched: Number of distinct community IDs present in the
        final node list.
    budget_used: Estimated tokens consumed by the returned nodes.
    budget_limit: ``BudgetConfig.max_tokens`` value used for this query.
    truncated: ``True`` if the result was cut short by the token budget.
