---
type: Wiki Entity
title: ResolutionConfig
id: class:parrot.knowledge.graphindex.resolve.ResolutionConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for cross-domain resolution.
---

# ResolutionConfig

Defined in [`parrot.knowledge.graphindex.resolve`](../summaries/mod:parrot.knowledge.graphindex.resolve.md).

```python
class ResolutionConfig
```

Configuration for cross-domain resolution.

Args:
    threshold: Global cosine similarity threshold.  Pairs with similarity
        above this value will produce ``mentions`` edges.
    max_edges_per_node: Maximum number of inferred edges per source node
        to prevent combinatorial explosion.
