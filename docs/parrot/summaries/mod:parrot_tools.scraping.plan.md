---
type: Wiki Summary
title: parrot_tools.scraping.plan
id: mod:parrot_tools.scraping.plan
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ScrapingPlan & PlanRegistryEntry Models.
relates_to:
- concept: class:parrot_tools.scraping.plan.PlanRegistryEntry
  rel: defines
- concept: class:parrot_tools.scraping.plan.ScrapingPlan
  rel: defines
---

# `parrot_tools.scraping.plan`

ScrapingPlan & PlanRegistryEntry Models.

Pydantic v2 models for declarative scraping plans and registry index entries.
ScrapingPlan is a value object — immutable once saved to disk.

## Classes

- **`ScrapingPlan(BaseModel)`** — Declarative scraping plan — value object, immutable once saved.
- **`PlanRegistryEntry(BaseModel)`** — Entry in the PlanRegistry index mapping a plan to its disk location.
