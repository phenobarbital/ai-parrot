---
type: Wiki Entity
title: GridType
id: class:parrot_pipelines.planogram.grid.models.GridType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Supported grid decomposition strategies.
---

# GridType

Defined in [`parrot_pipelines.planogram.grid.models`](../summaries/mod:parrot_pipelines.planogram.grid.models.md).

```python
class GridType(str, Enum)
```

Supported grid decomposition strategies.

Determines how the ROI is split into detection cells before LLM calls.
