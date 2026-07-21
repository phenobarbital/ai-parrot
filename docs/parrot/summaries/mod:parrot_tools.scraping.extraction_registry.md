---
type: Wiki Summary
title: parrot_tools.scraping.extraction_registry
id: mod:parrot_tools.scraping.extraction_registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ExtractionPlanRegistry — Disk-backed registry for ExtractionPlans.
relates_to:
- concept: class:parrot_tools.scraping.extraction_registry.ExtractionPlanRegistry
  rel: defines
- concept: mod:parrot_tools.scraping.base_registry
  rel: references
- concept: mod:parrot_tools.scraping.extraction_models
  rel: references
- concept: mod:parrot_tools.scraping.plan
  rel: references
---

# `parrot_tools.scraping.extraction_registry`

ExtractionPlanRegistry — Disk-backed registry for ExtractionPlans.

Extends ``BasePlanRegistry`` with extraction-specific lifecycle management:
  - success/failure tracking with automatic invalidation after 3 consecutive
    failures; counts are persisted in the registry index so they survive
    process restarts
  - per-fingerprint JSON file storage
  - pre-built plan loading from a developer-curated directory
  - lazy load: index + pre-built plans are loaded on first ``lookup_plan()``
    call so the async-incompatible ``__init__`` stays sync

## Classes

- **`ExtractionPlanRegistry(BasePlanRegistry[ExtractionPlan])`** — Disk-backed registry for ExtractionPlans with cache lifecycle management.
