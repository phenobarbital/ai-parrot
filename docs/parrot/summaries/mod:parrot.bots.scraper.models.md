---
type: Wiki Summary
title: parrot.bots.scraper.models
id: mod:parrot.bots.scraper.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.bots.scraper.models
relates_to:
- concept: class:parrot.bots.scraper.models.BrowserConfigSchema
  rel: defines
- concept: class:parrot.bots.scraper.models.ScrapingPlanSchema
  rel: defines
- concept: class:parrot.bots.scraper.models.ScrapingSelectorSchema
  rel: defines
- concept: class:parrot.bots.scraper.models.ScrapingStepSchema
  rel: defines
---

# `parrot.bots.scraper.models`

## Classes

- **`ScrapingStepSchema(BaseModel)`** — Schema for a single scraping step
- **`ScrapingSelectorSchema(BaseModel)`** — Schema for content extraction selector
- **`BrowserConfigSchema(BaseModel)`** — Schema for browser configuration
- **`ScrapingPlanSchema(BaseModel)`** — Complete scraping plan with steps, selectors, and config
