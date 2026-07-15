---
type: Wiki Summary
title: parrot.handlers.scraping
id: mod:parrot.handlers.scraping
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Scraping HTTP handlers for exposing WebScrapingToolkit over REST API.
relates_to:
- concept: func:parrot.handlers.scraping.setup_scraping_routes
  rel: defines
- concept: mod:parrot.handlers
  rel: references
- concept: mod:parrot.handlers.models
  rel: references
---

# `parrot.handlers.scraping`

Scraping HTTP handlers for exposing WebScrapingToolkit over REST API.

## Functions

- `def setup_scraping_routes(app: web.Application) -> None` — Register all scraping handler routes on the aiohttp application.
