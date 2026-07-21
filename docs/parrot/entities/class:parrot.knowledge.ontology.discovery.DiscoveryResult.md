---
type: Wiki Entity
title: DiscoveryResult
id: class:parrot.knowledge.ontology.discovery.DiscoveryResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of a relation discovery operation.
---

# DiscoveryResult

Defined in [`parrot.knowledge.ontology.discovery`](../summaries/mod:parrot.knowledge.ontology.discovery.md).

```python
class DiscoveryResult(BaseModel)
```

Result of a relation discovery operation.

Args:
    confirmed: Edges to create (list of {_from, _to, confidence, rule} dicts).
    review_queue: Ambiguous pairs below threshold.
    stats: Discovery statistics.
