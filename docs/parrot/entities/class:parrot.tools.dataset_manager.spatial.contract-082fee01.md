---
type: Wiki Entity
title: SpatialLayerResult
id: class:parrot.tools.dataset_manager.spatial.contracts.SpatialLayerResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-dataset slice of a spatial filter result (FEAT-221 G4).
---

# SpatialLayerResult

Defined in [`parrot.tools.dataset_manager.spatial.contracts`](../summaries/mod:parrot.tools.dataset_manager.spatial.contracts.md).

```python
class SpatialLayerResult(BaseModel)
```

Per-dataset slice of a spatial filter result (FEAT-221 G4).

Attributes:
    layer: Leaflet layer id / GeoJSON source discriminator (from DatasetSpatialProfile).
    features: GeoJSON Feature dicts for this dataset.
    total_count: True count of matching features before capping.
    capped: True when the result was truncated at the hard cap.
    geodesic: Whether the executed path was geodesic (True) or
        spherical-approximate (False).
