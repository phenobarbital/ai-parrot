---
type: Wiki Summary
title: parrot.outputs.formats.mixins.emaps
id: mod:parrot.outputs.formats.mixins.emaps
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ECharts Geo Extension for AI-Parrot
relates_to:
- concept: class:parrot.outputs.formats.mixins.emaps.CoordinateValidator
  rel: defines
- concept: class:parrot.outputs.formats.mixins.emaps.EChartsGeoBuilder
  rel: defines
- concept: class:parrot.outputs.formats.mixins.emaps.EChartsMapsMixin
  rel: defines
- concept: func:parrot.outputs.formats.mixins.emaps.get_echarts_system_prompt_with_geo
  rel: defines
---

# `parrot.outputs.formats.mixins.emaps`

ECharts Geo Extension for AI-Parrot
Adds geographic visualization capabilities to EChartsRenderer

## Classes

- **`CoordinateValidator`** — Validates and transforms geographic coordinates for ECharts
- **`EChartsGeoBuilder`** — Helper class to build ECharts geo configurations programmatically
- **`EChartsMapsMixin`** — Mixin class to add geo/map capabilities to EChartsRenderer

## Functions

- `def get_echarts_system_prompt_with_geo(base_prompt: str) -> str` — Combine base ECharts prompt with geo extension
