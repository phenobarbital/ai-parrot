---
type: Wiki Entity
title: StructuredMapConfig
id: class:parrot.models.outputs.StructuredMapConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Framework-agnostic map configuration for FEAT-221.
---

# StructuredMapConfig

Defined in [`parrot.models.outputs`](../summaries/mod:parrot.models.outputs.md).

```python
class StructuredMapConfig(BaseModel)
```

Framework-agnostic map configuration for FEAT-221.

Mirrors ``StructuredTableConfig``/``StructuredChartConfig`` — accepts data
on input (for column-name validation), but the renderer excludes the ``data``
field from the serialized output and routes per-layer payloads to
``response.data`` instead.

Attributes:
    layers: One ``MapLayer`` per dataset with data-schema + presentation hints.
    data: Flat tabular rows — INPUT-ONLY; excluded from ``output``,
        routed to ``response.data`` by the renderer.
    datasets: Per-layer GeoJSON/rows payloads — INCLUDED in ``output``
        (unlike ``data``); stripped from the FEAT-224 artifact definition
        to keep chat storage lean.
    viewport: Viewport hints (bbox + optional center/zoom).
    query: Echoed ``SpatialFilterSpec`` parameters (point / radius / unit).
    base_layer: Optional base-tile/style hint for the frontend (e.g. an OSM
        tile URL template or a Mapbox style id).
    title: Short map title.
    description: Short prose description.
    explanation: Longer LLM-authored prose explanation of the spatial result.
