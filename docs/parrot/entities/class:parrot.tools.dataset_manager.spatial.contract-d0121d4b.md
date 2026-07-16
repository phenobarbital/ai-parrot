---
type: Wiki Entity
title: DatasetSpatialProfile
id: class:parrot.tools.dataset_manager.spatial.contracts.DatasetSpatialProfile
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Describes how a specific dataset exposes its geometry.
---

# DatasetSpatialProfile

Defined in [`parrot.tools.dataset_manager.spatial.contracts`](../summaries/mod:parrot.tools.dataset_manager.spatial.contracts.md).

```python
class DatasetSpatialProfile(BaseModel)
```

Describes how a specific dataset exposes its geometry.

Each dataset that participates in spatial queries must have a profile
registered in SPATIAL_PROFILE_REGISTRY.  Profiles are I/O-free; they
carry only structural metadata.

Attributes:
    dataset: FK to a registered dataset name (must exist at execute time).
    lat_col: Latitude column name (naive lat/lng pair).
    lng_col: Longitude column name (naive lat/lng pair).
    geom_col: Native geometry or geography column.  Mutually exclusive with
        lat_col/lng_col when used for push-down — the compiler picks the
        appropriate path.
    layer: Leaflet layer id / GeoJSON ``source`` discriminator.
    property_cols: Column names to include in GeoJSON feature.properties.
    description_template: Python ``str.format_map`` template, e.g. ``"{name} ({type})"``.
    geodesic: Declared hint.  True = profile expects geodesic (native geography)
        precision; the compiler verifies this against the actual column type.
