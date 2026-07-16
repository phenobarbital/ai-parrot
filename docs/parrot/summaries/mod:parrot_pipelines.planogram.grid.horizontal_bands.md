---
type: Wiki Summary
title: parrot_pipelines.planogram.grid.horizontal_bands
id: mod:parrot_pipelines.planogram.grid.horizontal_bands
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HorizontalBands grid strategy for product-on-shelves planograms.
relates_to:
- concept: class:parrot_pipelines.planogram.grid.horizontal_bands.HorizontalBands
  rel: defines
- concept: mod:parrot_pipelines.planogram.grid.models
  rel: references
- concept: mod:parrot_pipelines.planogram.grid.strategy
  rel: references
---

# `parrot_pipelines.planogram.grid.horizontal_bands`

HorizontalBands grid strategy for product-on-shelves planograms.

Splits the ROI into N horizontal bands based on shelf height_ratios from
the planogram description. Each band becomes an independent detection cell
with focused product hints for that shelf level.

## Classes

- **`HorizontalBands(AbstractGridStrategy)`** — Grid strategy that decomposes the ROI into horizontal shelf bands.
