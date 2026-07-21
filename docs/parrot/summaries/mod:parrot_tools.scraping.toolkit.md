---
type: Wiki Summary
title: parrot_tools.scraping.toolkit
id: mod:parrot_tools.scraping.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WebScrapingToolkit — AbstractToolkit-based entry point for scraping.
relates_to:
- concept: class:parrot_tools.scraping.toolkit.ExtractionScore
  rel: defines
- concept: class:parrot_tools.scraping.toolkit.WebScrapingToolkit
  rel: defines
- concept: mod:parrot.tools.toolkit
  rel: references
- concept: mod:parrot_tools.scraping
  rel: references
- concept: mod:parrot_tools.scraping.driver_context
  rel: references
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: references
- concept: mod:parrot_tools.scraping.executor
  rel: references
- concept: mod:parrot_tools.scraping.models
  rel: references
- concept: mod:parrot_tools.scraping.page_snapshot
  rel: references
- concept: mod:parrot_tools.scraping.plan
  rel: references
- concept: mod:parrot_tools.scraping.plan_generator
  rel: references
- concept: mod:parrot_tools.scraping.plan_io
  rel: references
- concept: mod:parrot_tools.scraping.registry
  rel: references
- concept: mod:parrot_tools.scraping.toolkit_models
  rel: references
---

# `parrot_tools.scraping.toolkit`

WebScrapingToolkit — AbstractToolkit-based entry point for scraping.

Each public async method is automatically exposed as an individual tool
for agents and chatbots via ``AbstractToolkit``.

## Classes

- **`ExtractionScore`** — Heuristic quality score for a ``ScrapingResult``.
- **`WebScrapingToolkit(AbstractToolkit)`** — Toolkit for intelligent web scraping and crawling with plan caching.
