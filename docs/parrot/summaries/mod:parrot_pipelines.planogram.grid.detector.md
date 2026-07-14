---
type: Wiki Summary
title: parrot_pipelines.planogram.grid.detector
id: mod:parrot_pipelines.planogram.grid.detector
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Grid-based detection orchestrator.
relates_to:
- concept: class:parrot_pipelines.planogram.grid.detector.GridDetector
  rel: defines
- concept: mod:parrot.models.detections
  rel: references
- concept: mod:parrot_pipelines.planogram.grid.merger
  rel: references
- concept: mod:parrot_pipelines.planogram.grid.models
  rel: references
---

# `parrot_pipelines.planogram.grid.detector`

Grid-based detection orchestrator.

Orchestrates parallel per-cell LLM detection calls for grid-decomposed
planogram compliance pipelines.

Flow:
    1. For each GridCell: crop image, downscale, build focused prompt
    2. Filter reference images to cell's expected products
    3. Execute all cell calls in parallel via asyncio.gather()
    4. Handle per-cell failures (log and skip — don't block others)
    5. Parse raw LLM dicts into IdentifiedProduct with cell-relative coords
    6. Pass to CellResultMerger for offset correction + IoU deduplication

## Classes

- **`GridDetector`** — Orchestrates parallel per-cell LLM detection calls.
