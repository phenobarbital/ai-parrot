---
type: Wiki Summary
title: parrot_pipelines.planogram.types.product_counter
id: mod:parrot_pipelines.planogram.types.product_counter
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ProductCounter planogram type composable.
relates_to:
- concept: class:parrot_pipelines.planogram.types.product_counter.ProductCounter
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

# `parrot_pipelines.planogram.types.product_counter`

ProductCounter planogram type composable.

Handles planogram compliance for product-on-counter displays: a single
product placed on a counter/podium with a promotional background and an
information label.  No shelves, no grid — compliance is scored by element
presence alone.

## Classes

- **`ProductCounter(AbstractPlanogramType)`** — Planogram type for product-on-counter/podium displays.
