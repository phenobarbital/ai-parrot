---
type: Concept
title: compute_analytics()
id: func:parrot.knowledge.graphindex.analytics.compute_analytics
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute centrality metrics and rank cross-domain connections.
---

# compute_analytics

```python
def compute_analytics(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], edges: list[UniversalEdge], top_k: int=10) -> AnalyticsResult
```

Compute centrality metrics and rank cross-domain connections.

Args:
    graph: The assembled ``rustworkx.PyDiGraph`` instance.  Node
        payloads must be dicts with at least ``node_id``, ``kind``,
        and ``title`` keys.
    nodes: All ``UniversalNode`` objects in the graph (used for
        question generation).
    edges: All ``UniversalEdge`` objects (used to rank surprising
        connections from ``mentions`` edges).
    top_k: Number of top results to return for god-nodes and
        surprising connections.

Returns:
    An ``AnalyticsResult`` with god-nodes, surprising connections,
    suggested questions, and knowledge gaps.
