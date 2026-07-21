---
type: Wiki Summary
title: parrot_tools.scraping.toolkit_models
id: mod:parrot_tools.scraping.toolkit_models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit data models for WebScrapingToolkit.
relates_to:
- concept: class:parrot_tools.scraping.toolkit_models.DriverConfig
  rel: defines
- concept: class:parrot_tools.scraping.toolkit_models.PlanSaveResult
  rel: defines
- concept: class:parrot_tools.scraping.toolkit_models.PlanSummary
  rel: defines
---

# `parrot_tools.scraping.toolkit_models`

Toolkit data models for WebScrapingToolkit.

Provides DriverConfig (browser configuration), PlanSummary (slim registry
projection), and PlanSaveResult (plan save operation result).

## Classes

- **`DriverConfig(BaseModel)`** — Frozen browser configuration passed to the driver factory.
- **`PlanSummary(BaseModel)`** — Slim projection of PlanRegistryEntry for plan listing results.
- **`PlanSaveResult(BaseModel)`** — Result of a plan save operation.
