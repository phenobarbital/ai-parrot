---
type: Wiki Entity
title: ExpansionConfig
id: class:parrot.knowledge.graphindex.retriever.ExpansionConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for the graph expansion phase (Phase 2).
---

# ExpansionConfig

Defined in [`parrot.knowledge.graphindex.retriever`](../summaries/mod:parrot.knowledge.graphindex.retriever.md).

```python
class ExpansionConfig(BaseModel)
```

Configuration for the graph expansion phase (Phase 2).

Args:
    max_hops: Maximum number of hops to traverse outward from each seed.
        Must be between 1 and 4.
    decay_base: Multiplicative decay applied per hop.  A seed node at hop
        distance *h* has its parent's combined score multiplied by
        ``decay_base^h``.  Default ``0.7`` so hop 1 → 0.7, hop 2 → 0.49.
    min_signal_threshold: Neighbours with a ``SignalRelevance.combined``
        score strictly below this value are ignored during expansion.
    max_expanded_nodes: Hard cap on the total number of nodes (seeds +
        expanded) carried into Phase 3.  Expansion stops early when
        reached.
    include_community_centroids: When ``True`` and a ``CommunitiesResult``
        is available, add the centroid node of each touched community to
        the result set if not already present.
