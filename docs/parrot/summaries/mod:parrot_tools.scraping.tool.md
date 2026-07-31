---
type: Wiki Summary
title: parrot_tools.scraping.tool
id: mod:parrot_tools.scraping.tool
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WebScrapingTool for AI-Parrot
relates_to:
- concept: class:parrot_tools.scraping.tool.WebScrapingTool
  rel: defines
- concept: class:parrot_tools.scraping.tool.WebScrapingToolArgs
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.scraping.advanced_actions
  rel: references
- concept: mod:parrot_tools.scraping.crawl_graph
  rel: references
- concept: mod:parrot_tools.scraping.crawl_strategy
  rel: references
- concept: mod:parrot_tools.scraping.crawler
  rel: references
- concept: mod:parrot_tools.scraping.driver
  rel: references
- concept: mod:parrot_tools.scraping.driver_factory
  rel: references
- concept: mod:parrot_tools.scraping.models
  rel: references
- concept: mod:parrot_tools.scraping.plan
  rel: references
- concept: mod:parrot_tools.scraping.plan_io
  rel: references
- concept: mod:parrot_tools.scraping.registry
  rel: references
---

# `parrot_tools.scraping.tool`

WebScrapingTool for AI-Parrot
Combines Selenium/Playwright automation with LLM-directed scraping

## Classes

- **`WebScrapingToolArgs(BaseModel)`** — Arguments schema for WebScrapingTool.
- **`WebScrapingTool(AbstractTool)`** — Advanced web scraping tool with LLM integration support.
