---
type: Wiki Summary
title: parrot.handlers.scraping.models
id: mod:parrot.handlers.scraping.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic request/response models for the Scraping HTTP API.
relates_to:
- concept: class:parrot.handlers.scraping.models.ActionInfo
  rel: defines
- concept: class:parrot.handlers.scraping.models.CrawlRequest
  rel: defines
- concept: class:parrot.handlers.scraping.models.DriverTypeInfo
  rel: defines
- concept: class:parrot.handlers.scraping.models.PlanCreateRequest
  rel: defines
- concept: class:parrot.handlers.scraping.models.PlanSaveRequest
  rel: defines
- concept: class:parrot.handlers.scraping.models.ScrapeRequest
  rel: defines
- concept: class:parrot.handlers.scraping.models.StrategyInfo
  rel: defines
---

# `parrot.handlers.scraping.models`

Pydantic request/response models for the Scraping HTTP API.

These models define the data contract between the navigator-frontend-next
ScrapingToolkit Svelte UI and the scraping handler endpoints at /api/v1/scraping/.

## Classes

- **`PlanCreateRequest(BaseModel)`** — Request body for POST /api/v1/scraping/plans (create a new plan via LLM).
- **`ScrapeRequest(BaseModel)`** — Request body for POST /api/v1/scraping/scrape.
- **`CrawlRequest(BaseModel)`** — Request body for POST /api/v1/scraping/crawl.
- **`PlanSaveRequest(BaseModel)`** — Request body for PUT /api/v1/scraping/plans/{name} (save/update a plan).
- **`ActionInfo(BaseModel)`** — Description of a single browser action type for the UI.
- **`DriverTypeInfo(BaseModel)`** — Available driver type and its supported browsers.
- **`StrategyInfo(BaseModel)`** — Crawl strategy description for the UI.
