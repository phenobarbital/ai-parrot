---
type: Wiki Entity
title: KnowledgeGaps
id: class:parrot.knowledge.graphindex.analytics.KnowledgeGaps
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Aggregated knowledge gap report.
---

# KnowledgeGaps

Defined in [`parrot.knowledge.graphindex.analytics`](../summaries/mod:parrot.knowledge.graphindex.analytics.md).

```python
class KnowledgeGaps(BaseModel)
```

Aggregated knowledge gap report.

Args:
    isolated_nodes: Nodes with degree <= max_degree (few connections).
    sparse_communities: Communities with low cohesion and sufficient size.
    bridge_nodes: Nodes that connect many distinct communities.
