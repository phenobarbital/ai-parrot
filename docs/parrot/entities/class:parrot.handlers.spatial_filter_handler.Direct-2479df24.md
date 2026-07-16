---
type: Wiki Entity
title: DirectSpatialRequest
id: class:parrot.handlers.spatial_filter_handler.DirectSpatialRequest
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Request body for the direct (deterministic) spatial filter path.
---

# DirectSpatialRequest

Defined in [`parrot.handlers.spatial_filter_handler`](../summaries/mod:parrot.handlers.spatial_filter_handler.md).

```python
class DirectSpatialRequest(BaseModel)
```

Request body for the direct (deterministic) spatial filter path.

Attributes:
    point: ``[lat, lng]`` in decimal degrees.
    radius: Search radius.
    unit: Distance unit.
    datasets: Dataset names to query.
    cap_per_dataset: Hard cap per dataset (optional).
