---
type: Wiki Entity
title: MapQuery
id: class:parrot.models.outputs.MapQuery
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Echoed spatial filter query — carries the originating search parameters (FEAT-221).
---

# MapQuery

Defined in [`parrot.models.outputs`](../summaries/mod:parrot.models.outputs.md).

```python
class MapQuery(BaseModel)
```

Echoed spatial filter query — carries the originating search parameters (FEAT-221).

Attributes:
    point: (lat, lng) echoed from ``SpatialFilterSpec.point``.
    radius: Search radius.
    unit: Distance unit.
