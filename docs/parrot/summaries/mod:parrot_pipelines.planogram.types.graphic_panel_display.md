---
type: Wiki Summary
title: parrot_pipelines.planogram.types.graphic_panel_display
id: mod:parrot_pipelines.planogram.types.graphic_panel_display
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GraphicPanelDisplay planogram type composable.
relates_to:
- concept: class:parrot_pipelines.planogram.types.graphic_panel_display.GraphicPanelDisplay
  rel: defines
- concept: mod:parrot.models.compliance
  rel: references
- concept: mod:parrot.models.detections
  rel: references
- concept: mod:parrot.models.google
  rel: references
- concept: mod:parrot_pipelines.planogram.types.abstract
  rel: references
---

# `parrot_pipelines.planogram.types.graphic_panel_display`

GraphicPanelDisplay planogram type composable.

Handles planogram compliance for graphic-panel / signage endcap displays
(EcoTank endcaps, projector displays, Bose audio displays, etc.).

These displays contain no physical products — compliance is determined by
verifying that the correct graphic zones are present in the correct
positions, with the correct text content and (where applicable) the
correct illumination state.

## Classes

- **`GraphicPanelDisplay(AbstractPlanogramType)`** — Composable type for graphic-panel / signage endcap compliance.
