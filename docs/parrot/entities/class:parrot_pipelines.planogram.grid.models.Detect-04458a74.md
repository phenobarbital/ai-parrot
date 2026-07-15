---
type: Wiki Entity
title: DetectionGridConfig
id: class:parrot_pipelines.planogram.grid.models.DetectionGridConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for detection grid decomposition.
---

# DetectionGridConfig

Defined in [`parrot_pipelines.planogram.grid.models`](../summaries/mod:parrot_pipelines.planogram.grid.models.md).

```python
class DetectionGridConfig(BaseModel)
```

Configuration for detection grid decomposition.

Added as an optional field to PlanogramConfig.
When None or grid_type='no_grid', pipeline uses current single-image behavior.
