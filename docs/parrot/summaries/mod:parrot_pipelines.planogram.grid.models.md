---
type: Wiki Summary
title: parrot_pipelines.planogram.grid.models
id: mod:parrot_pipelines.planogram.grid.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Detection grid data models.
relates_to:
- concept: class:parrot_pipelines.planogram.grid.models.DetectionGridConfig
  rel: defines
- concept: class:parrot_pipelines.planogram.grid.models.GridCell
  rel: defines
- concept: class:parrot_pipelines.planogram.grid.models.GridType
  rel: defines
---

# `parrot_pipelines.planogram.grid.models`

Detection grid data models.

Provides Pydantic models for the adaptive grid detection system:
- GridType: supported decomposition strategies
- DetectionGridConfig: configuration for grid decomposition
- GridCell: a single cell in the detection grid

## Classes

- **`GridType(str, Enum)`** — Supported grid decomposition strategies.
- **`DetectionGridConfig(BaseModel)`** — Configuration for detection grid decomposition.
- **`GridCell(BaseModel)`** — A single cell in the detection grid.
