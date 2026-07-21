---
type: Wiki Entity
title: SpatialFilterSpec
id: class:parrot.tools.dataset_manager.spatial.contracts.SpatialFilterSpec
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Describes a spatial radius filter request.
---

# SpatialFilterSpec

Defined in [`parrot.tools.dataset_manager.spatial.contracts`](../summaries/mod:parrot.tools.dataset_manager.spatial.contracts.md).

```python
class SpatialFilterSpec(BaseModel)
```

Describes a spatial radius filter request.

Backend-agnostic: carries no driver, DSN, or SQL.  Emitted identically
by the LLM (NL→spec mode) and the frontend (deterministic mode).

Attributes:
    point: (lat, lng) in decimal degrees.
    radius: Search radius in the specified unit.
    unit: Distance unit — "mi", "km", or "m".
    datasets: Dataset names to query (resolved via DatasetManager._resolve_name).
