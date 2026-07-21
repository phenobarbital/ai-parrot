---
type: Wiki Summary
title: parrot.outputs.a2ui.catalog.components.chart
id: mod:parrot.outputs.a2ui.catalog.components.chart
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2UI ``Chart`` catalog component (Module 3).
relates_to:
- concept: class:parrot.outputs.a2ui.catalog.components.chart.ChartComponent
  rel: defines
- concept: mod:parrot.outputs.a2ui.catalog
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.base
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
---

# `parrot.outputs.a2ui.catalog.components.chart`

A2UI ``Chart`` catalog component (Module 3).

Schema vocabulary is adapted from ``StructuredChartConfig``
(``parrot.models.outputs`` — FEAT-218/221): ``type``, ``x``, ``y``, ``stacked``,
``showLegend``, ``xAxisMode``, ``palette``. The Pydantic class is NOT imported into
the wire format; only its field vocabulary is mirrored into the JSON Schema.

In A2UI the config's INPUT-ONLY ``data`` array is replaced by a data-model binding:
rows are bound via a ``{"$bind": "/pointer"}`` expression, resolved in the Module 6
bake pass. ECharts option-building is renderer-side (satellite) — the lowered tree
here contains only Basic Catalog primitives.

## Classes

- **`ChartComponent`** — The ``Chart`` catalog component (display-only, ``requires_actions=False``).
