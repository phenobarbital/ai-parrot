---
type: Wiki Summary
title: parrot_pipelines.planogram.types.product_on_shelves
id: mod:parrot_pipelines.planogram.types.product_on_shelves
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ProductOnShelves planogram type composable.
relates_to:
- concept: class:parrot_pipelines.planogram.types.product_on_shelves.ProductOnShelves
  rel: defines
- concept: mod:parrot.models.compliance
  rel: references
- concept: mod:parrot.models.detections
  rel: references
- concept: mod:parrot.models.google
  rel: references
- concept: mod:parrot_pipelines.planogram.grid.detector
  rel: references
- concept: mod:parrot_pipelines.planogram.grid.horizontal_bands
  rel: references
- concept: mod:parrot_pipelines.planogram.grid.models
  rel: references
- concept: mod:parrot_pipelines.planogram.grid.strategy
  rel: references
- concept: mod:parrot_pipelines.planogram.types.abstract
  rel: references
---

# `parrot_pipelines.planogram.types.product_on_shelves`

ProductOnShelves planogram type composable.

Handles planogram compliance for product-on-shelves displays (endcaps with
poster/header panels and shelved products below).

## Classes

- **`ProductOnShelves(AbstractPlanogramType)`** — Planogram type for product-on-shelves displays.
