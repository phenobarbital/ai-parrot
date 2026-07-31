---
type: Wiki Entity
title: NLSpatialRequest
id: class:parrot.handlers.spatial_filter_handler.NLSpatialRequest
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Request body for the NL→spec synthesis spatial filter path.
---

# NLSpatialRequest

Defined in [`parrot.handlers.spatial_filter_handler`](../summaries/mod:parrot.handlers.spatial_filter_handler.md).

```python
class NLSpatialRequest(BaseModel)
```

Request body for the NL→spec synthesis spatial filter path.

Attributes:
    query: Natural language spatial query.
    datasets: Optional hint about which datasets to query.
    cap_per_dataset: Hard cap per dataset.
