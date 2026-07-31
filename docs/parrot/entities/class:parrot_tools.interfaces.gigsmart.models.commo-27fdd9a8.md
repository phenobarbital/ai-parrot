---
type: Wiki Entity
title: RelayEdge
id: class:parrot_tools.interfaces.gigsmart.models.common.RelayEdge
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single edge in a Relay connection.
---

# RelayEdge

Defined in [`parrot_tools.interfaces.gigsmart.models.common`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.common.md).

```python
class RelayEdge(BaseModel, Generic[T])
```

A single edge in a Relay connection.

Args:
    node: The actual resource payload.
    cursor: Opaque pagination cursor for this edge.
