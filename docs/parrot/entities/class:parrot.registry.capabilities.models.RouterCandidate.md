---
type: Wiki Entity
title: RouterCandidate
id: class:parrot.registry.capabilities.models.RouterCandidate
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A scored match from capability search.
---

# RouterCandidate

Defined in [`parrot.registry.capabilities.models`](../summaries/mod:parrot.registry.capabilities.models.md).

```python
class RouterCandidate(BaseModel)
```

A scored match from capability search.

Args:
    entry: The matched capability entry.
    score: Cosine similarity score in [0.0, 1.0].
    resource_type: The resource type of the matched entry.
