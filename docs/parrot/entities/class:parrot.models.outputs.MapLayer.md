---
type: Wiki Entity
title: MapLayer
id: class:parrot.models.outputs.MapLayer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: One layer per dataset — data schema + presentation schema (FEAT-221).
---

# MapLayer

Defined in [`parrot.models.outputs`](../summaries/mod:parrot.models.outputs.md).

```python
class MapLayer(BaseModel)
```

One layer per dataset — data schema + presentation schema (FEAT-221).

Attributes:
    layer: Leaflet layer id / GeoJSON source discriminator.
    columns: Per-column contract for this layer (name / type / title / format).
    tooltip_template: Python ``str.format_map`` template applied client-side
        over ``feature.properties`` (compact, G8 — no per-element strings).
    label_field: Property key used for the marker label.
    data_shape: Per-layer data payload shape: ``"geojson"`` passes features
        through; ``"rows"`` flattens to canonical row dicts (G6).
    total_count: Per-dataset true count before capping (G10).
    capped: True when the per-dataset result was truncated at the hard cap.
    geodesic: Whether the executed path was geodesic (True) or
        spherical-approximate (False). Sourced from ``SpatialLayerResult``.
    marker_color: Optional marker/pin color for every feature in this layer,
        derived from the user's request (piggyback — no extra LLM call). A
        canonical CSS color name (e.g. ``"red"``, ``"blue"``) or a hex string
        (e.g. ``"#1f77b4"``). ``None`` = the frontend uses its default marker
        color.
