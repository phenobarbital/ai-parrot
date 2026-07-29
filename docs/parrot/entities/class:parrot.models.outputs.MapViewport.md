---
type: Wiki Entity
title: MapViewport
id: class:parrot.models.outputs.MapViewport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Map viewport hints — computed from feature bounds (FEAT-221).
---

# MapViewport

Defined in [`parrot.models.outputs`](../summaries/mod:parrot.models.outputs.md).

```python
class MapViewport(BaseModel)
```

Map viewport hints — computed from feature bounds (FEAT-221).

Attributes:
    bbox: [min_lng, min_lat, max_lng, max_lat] bounding box.
    center: (lat, lng) optional center — frontend may derive from bbox.
    zoom: Optional zoom-level hint.
