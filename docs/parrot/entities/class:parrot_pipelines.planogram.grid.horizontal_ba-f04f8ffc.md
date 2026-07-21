---
type: Wiki Entity
title: HorizontalBands
id: class:parrot_pipelines.planogram.grid.horizontal_bands.HorizontalBands
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Grid strategy that decomposes the ROI into horizontal shelf bands.
relates_to:
- concept: class:parrot_pipelines.planogram.grid.strategy.AbstractGridStrategy
  rel: extends
---

# HorizontalBands

Defined in [`parrot_pipelines.planogram.grid.horizontal_bands`](../summaries/mod:parrot_pipelines.planogram.grid.horizontal_bands.md).

```python
class HorizontalBands(AbstractGridStrategy)
```

Grid strategy that decomposes the ROI into horizontal shelf bands.

Reads shelf configurations from PlanogramDescription to determine:
- The number of bands (N = number of configured shelves)
- Each band's vertical extent (proportional to shelf.height_ratio)
- Expected products per band (from shelf.products[].name)

An overlap margin is applied to extend each band's top/bottom boundary
so that products near cell boundaries are captured by both adjacent cells
and later deduplicated by CellResultMerger.

## Methods

- `def compute_cells(self, roi_bbox: tuple, image_size: tuple, planogram_description: Any, grid_config: DetectionGridConfig) -> List[GridCell]` — Decompose the ROI into horizontal shelf bands.
