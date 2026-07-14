---
type: Wiki Entity
title: RelayConnection
id: class:parrot_tools.interfaces.gigsmart.models.common.RelayConnection
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A Relay pagination connection wrapping a list of typed edges.
---

# RelayConnection

Defined in [`parrot_tools.interfaces.gigsmart.models.common`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.common.md).

```python
class RelayConnection(BaseModel, Generic[T])
```

A Relay pagination connection wrapping a list of typed edges.

Args:
    edges: List of :class:`RelayEdge` wrappers around the resource type.
    page_info: Pagination metadata for the current page.

## Methods

- `def nodes(self) -> list[T]` — Return the unwrapped list of node objects from all edges.
