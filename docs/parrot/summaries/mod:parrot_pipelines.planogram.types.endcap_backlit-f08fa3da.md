---
type: Wiki Summary
title: parrot_pipelines.planogram.types.endcap_backlit_multitier
id: mod:parrot_pipelines.planogram.types.endcap_backlit_multitier
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: EndcapBacklitMultitier planogram type composable.
relates_to:
- concept: class:parrot_pipelines.planogram.types.endcap_backlit_multitier.EndcapBacklitMultitier
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

# `parrot_pipelines.planogram.types.endcap_backlit_multitier`

EndcapBacklitMultitier planogram type composable.

Handles planogram compliance for backlit multi-tier endcap displays: a
retro-illuminated header panel (lightbox) combined with one or more product
shelves.  Shelves may be sub-divided into named sections detected in parallel.

## Classes

- **`EndcapBacklitMultitier(AbstractPlanogramType)`** — Planogram type for backlit multi-tier endcap displays.
