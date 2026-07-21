---
type: Wiki Entity
title: DiscoveryStats
id: class:parrot.knowledge.ontology.discovery.DiscoveryStats
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Statistics for a discovery run.
---

# DiscoveryStats

Defined in [`parrot.knowledge.ontology.discovery`](../summaries/mod:parrot.knowledge.ontology.discovery.md).

```python
class DiscoveryStats(BaseModel)
```

Statistics for a discovery run.

Args:
    total_source: Number of source records processed.
    total_target: Number of target records available.
    edges_created: Number of confirmed edges.
    needs_review: Number of ambiguous pairs sent to review queue.
