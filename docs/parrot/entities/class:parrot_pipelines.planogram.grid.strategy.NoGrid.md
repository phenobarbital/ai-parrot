---
type: Wiki Entity
title: NoGrid
id: class:parrot_pipelines.planogram.grid.strategy.NoGrid
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Default grid strategy — no decomposition.
relates_to:
- concept: class:parrot_pipelines.planogram.grid.strategy.AbstractGridStrategy
  rel: extends
---

# NoGrid

Defined in [`parrot_pipelines.planogram.grid.strategy`](../summaries/mod:parrot_pipelines.planogram.grid.strategy.md).

```python
class NoGrid(AbstractGridStrategy)
```

Default grid strategy — no decomposition.

Returns a single GridCell covering the entire ROI with all expected
products from all shelves. Preserves current single-image behavior.

## Methods

- `def compute_cells(self, roi_bbox: tuple, image_size: tuple, planogram_description: Any, grid_config: DetectionGridConfig) -> List[GridCell]` — Return a single cell covering the full ROI.
