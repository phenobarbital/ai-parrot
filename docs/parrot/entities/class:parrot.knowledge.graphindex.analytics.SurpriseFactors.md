---
type: Wiki Entity
title: SurpriseFactors
id: class:parrot.knowledge.graphindex.analytics.SurpriseFactors
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decomposed explanation of why a connection is surprising.
---

# SurpriseFactors

Defined in [`parrot.knowledge.graphindex.analytics`](../summaries/mod:parrot.knowledge.graphindex.analytics.md).

```python
class SurpriseFactors(BaseModel)
```

Decomposed explanation of why a connection is surprising.

Args:
    cross_community: Source and target in different Louvain communities.
    cross_type: Source and target have different NodeKind values.
    type_distance: Distance between node kinds (1 = adjacent, 2 = distant).
    peripheral_hub: Low-degree node connected to a high-degree hub.
    weak_but_present: Edge confidence below 0.5.
    high_confidence: Edge confidence >= 0.7.
    composite_score: Sum of all contributing signals.
