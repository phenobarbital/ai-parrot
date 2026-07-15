---
type: Wiki Summary
title: parrot.outputs.a2ui_renderers.echarts
id: mod:parrot.outputs.a2ui_renderers.echarts
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ECharts payload renderer (Module 5, satellite).
relates_to:
- concept: class:parrot.outputs.a2ui_renderers.echarts.EChartsRenderer
  rel: defines
- concept: mod:parrot.outputs.a2ui.artifacts
  rel: references
- concept: mod:parrot.outputs.a2ui.baking
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.components
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
- concept: mod:parrot.outputs.a2ui.renderers
  rel: references
---

# `parrot.outputs.a2ui_renderers.echarts`

ECharts payload renderer (Module 5, satellite).

Deterministic replacement for the legacy ``formats/echarts.py`` (which loaded ECharts
from a CDN). This renderer emits the ECharts **option JSON** as its primary output from
a baked ``Chart`` component's data; an optional HTML wrap inlines the *vendored*
``formats/assets/echarts.min.js`` bundle (never a CDN ``<script src>``).

Security (G1): no code strings, no ``exec``; the option payload is a plain dict built
from validated component data.

## Classes

- **`EChartsRenderer(AbstractA2UIRenderer)`** — Chart-component → ECharts option JSON renderer (+ optional vendored HTML wrap).
