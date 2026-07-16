---
type: Wiki Summary
title: parrot_pipelines.planogram.types.endcap_no_shelves_promotional
id: mod:parrot_pipelines.planogram.types.endcap_no_shelves_promotional
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: EndcapNoShelvesPromotional planogram type composable.
relates_to:
- concept: class:parrot_pipelines.planogram.types.endcap_no_shelves_promotional.EndcapNoShelvesPromotional
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

# `parrot_pipelines.planogram.types.endcap_no_shelves_promotional`

EndcapNoShelvesPromotional planogram type composable.

Handles planogram compliance for shelf-less promotional endcaps: a
retro-illuminated upper panel (brand/promo graphic) and a lower poster.
No physical products are expected — compliance is determined by verifying
that both zones are present and that the backlit panel is correctly
illuminated.

## Classes

- **`EndcapNoShelvesPromotional(AbstractPlanogramType)`** — Planogram type for shelf-less promotional endcap displays.
