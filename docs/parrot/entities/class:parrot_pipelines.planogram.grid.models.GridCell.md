---
type: Wiki Entity
title: GridCell
id: class:parrot_pipelines.planogram.grid.models.GridCell
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single cell in the detection grid.
---

# GridCell

Defined in [`parrot_pipelines.planogram.grid.models`](../summaries/mod:parrot_pipelines.planogram.grid.models.md).

```python
class GridCell(BaseModel)
```

A single cell in the detection grid.

Each cell represents an independent region of the ROI that will be
sent to the LLM as a separate detection call.
