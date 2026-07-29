---
type: Wiki Summary
title: parrot.handlers.scraping.info
id: mod:parrot.handlers.scraping.info
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ScrapingInfoHandler — GET-only reference metadata endpoints for the Scraping
  UI.
relates_to:
- concept: class:parrot.handlers.scraping.info.ScrapingInfoHandler
  rel: defines
- concept: mod:parrot.tools
  rel: references
---

# `parrot.handlers.scraping.info`

ScrapingInfoHandler — GET-only reference metadata endpoints for the Scraping UI.

Serves browser action catalog, driver types, driver configuration schema,
and crawl strategy definitions. Designed to be consumed by the ScrapingToolkit
Svelte component in navigator-frontend-next for dynamic form rendering.

## Classes

- **`ScrapingInfoHandler(BaseHandler)`** — Method-based handler serving reference data for the Scraping UI.
