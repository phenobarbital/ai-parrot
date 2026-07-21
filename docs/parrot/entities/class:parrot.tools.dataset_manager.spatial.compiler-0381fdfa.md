---
type: Wiki Entity
title: CompiledQuery
id: class:parrot.tools.dataset_manager.spatial.compiler.CompiledQuery
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Immutable result of SpatialCompiler.compile().
---

# CompiledQuery

Defined in [`parrot.tools.dataset_manager.spatial.compiler`](../summaries/mod:parrot.tools.dataset_manager.spatial.compiler.md).

```python
class CompiledQuery
```

Immutable result of SpatialCompiler.compile().

All fields are set at compile time; no I/O occurs during construction.

Attributes:
    sql: The SQL string to execute (engine push-down) or ``None`` for the
        in-memory fallback path.
    driver: Normalised AsyncDB driver name (``"pg"``, ``"bigquery"``,
        ``"mysql"``, or other).
    path: ``"engine"`` for pg/bigquery push-down; ``"pandas"`` for bbox fallback.
    geodesic: True if the executed path is geodesic (native geography column or
        BigQuery GEOGRAPHY).  False = spherical-approximate haversine.
    profile_dataset: The dataset name this compiled query is for.
    bbox: ``(min_lat, max_lat, min_lng, max_lng)`` for the pandas path (used in
        the BETWEEN predicate).  None for the engine path.
    lat_col: Latitude column name used in the fallback path.  None for engine path.
    lng_col: Longitude column name used in the fallback path.  None for engine path.
    point: ``(lat, lng)`` of the query centre point (used in haversine refine).
    radius_m: Search radius converted to metres.
    property_cols: Column names to include in GeoJSON feature properties.
    description_template: Python str.format_map template for feature description.
    geom_col: Geometry/geography column name for the engine path.
    cap: Maximum features to return for this dataset.
    geodesic_warning: Non-empty string if a geodesic mismatch was detected.
