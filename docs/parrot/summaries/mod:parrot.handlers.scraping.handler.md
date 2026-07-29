---
type: Wiki Summary
title: parrot.handlers.scraping.handler
id: mod:parrot.handlers.scraping.handler
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ScrapingHandler — Class-based HTTP view for plan CRUD and scrape/crawl execution.
relates_to:
- concept: class:parrot.handlers.scraping.handler.ScrapingHandler
  rel: defines
- concept: mod:parrot.handlers.jobs.job
  rel: references
- concept: mod:parrot.handlers.scraping.models
  rel: references
- concept: mod:parrot.tools
  rel: references
---

# `parrot.handlers.scraping.handler`

ScrapingHandler — Class-based HTTP view for plan CRUD and scrape/crawl execution.

Exposes the WebScrapingToolkit API over HTTP at /api/v1/scraping/.
Manages its own WebScrapingToolkit instance, JobManager for async execution,
and integrates with a BasicAgent for LLM-powered plan generation.

## Classes

- **`ScrapingHandler(BaseView)`** — Class-based HTTP view for /api/v1/scraping/.
