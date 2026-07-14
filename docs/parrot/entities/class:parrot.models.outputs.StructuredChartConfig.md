---
type: Wiki Entity
title: StructuredChartConfig
id: class:parrot.models.outputs.StructuredChartConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Library-agnostic chart configuration mirroring the frontend AppChartConfig.
---

# StructuredChartConfig

Defined in [`parrot.models.outputs`](../summaries/mod:parrot.models.outputs.md).

```python
class StructuredChartConfig(BaseModel)
```

Library-agnostic chart configuration mirroring the frontend AppChartConfig.

Accepts data rows on input (for column validation), but the renderer excludes
the ``data`` field from the serialized output — rows are routed to
``response.data`` instead (see StructuredChartRenderer).

Attributes:
    type: Chart type (e.g. "bar", "line", "map").
    x: Categorical/label column name.
    y: One or more value column names (multi-series).
    stacked: Whether to stack series (bar/area/line).
    trendline: Whether to render a trend line.
    split_series: Render each y series as a separate chart.
    show_legend: Whether to display the chart legend.
    x_axis_mode: Axis scale — "category" or "time" (ISO 8601 strings required).
    palette: Optional list of hex colour strings.
    color_by_sign: Colour bars/points by positive/negative value.
    negative_color: Hex colour for negative values when colorBySign is True.
    map_name: GeoJSON map identifier (required when type="map").
    data: Flat row list — INPUT-ONLY; excluded from output by the renderer.
