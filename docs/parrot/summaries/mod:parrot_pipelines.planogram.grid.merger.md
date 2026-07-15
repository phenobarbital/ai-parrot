---
type: Wiki Summary
title: parrot_pipelines.planogram.grid.merger
id: mod:parrot_pipelines.planogram.grid.merger
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Cell Result Merger for grid-based detection.
relates_to:
- concept: class:parrot_pipelines.planogram.grid.merger.CellResultMerger
  rel: defines
- concept: mod:parrot.models.detections
  rel: references
- concept: mod:parrot_pipelines.planogram.grid.models
  rel: references
---

# `parrot_pipelines.planogram.grid.merger`

Cell Result Merger for grid-based detection.

Merges per-cell detection results from parallel LLM calls into a
unified product list. Handles:
- Coordinate offset correction: cell-relative coords -> absolute image coords
- IoU-based boundary deduplication: removes duplicates at cell boundaries
- Out-of-place tagging: flags products detected in the wrong cell

## Classes

- **`CellResultMerger`** — Merges per-cell detection results into a unified product list.
