---
type: Wiki Summary
title: parrot_tools.scraping.base_registry
id: mod:parrot_tools.scraping.base_registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: BasePlanRegistry — Generic disk-backed plan registry.
relates_to:
- concept: class:parrot_tools.scraping.base_registry.BasePlanRegistry
  rel: defines
- concept: class:parrot_tools.scraping.base_registry.PlanLike
  rel: defines
- concept: mod:parrot_tools.scraping.plan
  rel: references
---

# `parrot_tools.scraping.base_registry`

BasePlanRegistry — Generic disk-backed plan registry.

Provides the shared 3-tier URL lookup and CRUD operations for all plan
registry types. Subclass with a concrete plan model (e.g. ``ScrapingPlan``
or ``ExtractionPlan``) to get a fully functional registry without
duplicating boilerplate.

## Classes

- **`PlanLike(Protocol)`** — Protocol that all registrable plan types must satisfy.
- **`BasePlanRegistry(Generic[T])`** — Generic disk-backed plan registry with 3-tier URL lookup.
