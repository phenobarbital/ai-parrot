---
type: Wiki Entity
title: SpatialResult
id: class:parrot.tools.dataset_manager.spatial.contracts.SpatialResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Versioned per-dataset result returned by spatial_filter (FEAT-221 G4).
---

# SpatialResult

Defined in [`parrot.tools.dataset_manager.spatial.contracts`](../summaries/mod:parrot.tools.dataset_manager.spatial.contracts.md).

```python
class SpatialResult(BaseModel)
```

Versioned per-dataset result returned by spatial_filter (FEAT-221 G4).

Replaces the merged ``SpatialFeatureCollection`` with per-dataset grouping.
The ``as_feature_collection()`` method reproduces the legacy merged shape for
backward-compatible callers (e.g. the transport handler).

Attributes:
    version: Schema version — always 2 for this model.
    layers: Per-dataset results keyed by resolved dataset name.

## Methods

- `def as_feature_collection(self) -> 'SpatialFeatureCollection'` — Reproduce the legacy merged SpatialFeatureCollection shape.
- `def from_dataframe(cls, df: Any, *, lat_col: Optional[str]=None, lon_col: Optional[str]=None, geometry_col: Optional[str]=None, dataset: str='result', layer: str='result', property_cols: Optional[List[str]]=None, geodesic: bool=False) -> 'SpatialResult'` — Build a single-layer ``SpatialResult`` from a pandas DataFrame.
