---
type: Wiki Entity
title: SpatialFeatureCollection
id: class:parrot.tools.dataset_manager.spatial.contracts.SpatialFeatureCollection
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: GeoJSON FeatureCollection returned by DatasetManager.spatial_filter.
---

# SpatialFeatureCollection

Defined in [`parrot.tools.dataset_manager.spatial.contracts`](../summaries/mod:parrot.tools.dataset_manager.spatial.contracts.md).

```python
class SpatialFeatureCollection(BaseModel)
```

GeoJSON FeatureCollection returned by DatasetManager.spatial_filter.

The shape is identical regardless of whether the query came from the LLM
(NL→spec) or the frontend (deterministic).  Frontend builds the map;
this model carries data only.

Attributes:
    type: GeoJSON type discriminator — always "FeatureCollection".
    features: List of GeoJSON Feature dicts.  Each feature has at least
        ``geometry``, ``properties`` (with data + ``description`` + ``source``),
        and ``type``.
    total_count: True count of matching features before capping.  May be
        greater than ``len(features)`` when capped.
    capped: True when the result was truncated at the hard cap.
    geodesic_paths: Per-dataset flag recording whether the executed path
        was geodesic (True) or spherical-approximate (False).
