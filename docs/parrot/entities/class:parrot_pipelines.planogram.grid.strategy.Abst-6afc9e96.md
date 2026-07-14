---
type: Wiki Entity
title: AbstractGridStrategy
id: class:parrot_pipelines.planogram.grid.strategy.AbstractGridStrategy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for grid decomposition strategies.
---

# AbstractGridStrategy

Defined in [`parrot_pipelines.planogram.grid.strategy`](../summaries/mod:parrot_pipelines.planogram.grid.strategy.md).

```python
class AbstractGridStrategy(ABC)
```

Base class for grid decomposition strategies.

Concrete strategies implement compute_cells() to split an ROI into
independent detection cells based on planogram configuration.

All strategies must be stateless — configuration is passed via
DetectionGridConfig at call time.

## Methods

- `def compute_cells(self, roi_bbox: tuple, image_size: tuple, planogram_description: Any, grid_config: DetectionGridConfig) -> List[GridCell]` — Decompose the ROI into grid cells for detection.
