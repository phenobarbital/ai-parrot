---
type: Wiki Summary
title: parrot_tools.rss.fetcher
id: mod:parrot_tools.rss.fetcher
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Article and feed fetching for the RSS Feed Reader Toolkit.
relates_to:
- concept: class:parrot_tools.rss.fetcher.ArticleFetcher
  rel: defines
- concept: func:parrot_tools.rss.fetcher.extract_text
  rel: defines
- concept: mod:parrot_tools.rss.models
  rel: references
- concept: mod:parrot_tools.scraping.driver
  rel: references
---

# `parrot_tools.rss.fetcher`

Article and feed fetching for the RSS Feed Reader Toolkit.

Strategy: fast aiohttp GET first; fall back to a shared headless Selenium
driver (reusing ``parrot_tools.scraping.driver.SeleniumSetup``, available via
the ``scraping`` extra) when the response fails or looks like a JS-rendered
shell. Feed XML parsing (feedparser) and all Selenium calls are blocking and
run off the event loop via ``asyncio.to_thread`` / ``run_in_executor``.

## Classes

- **`ArticleFetcher`** — Fetches feed XML and article pages with bounded concurrency.

## Functions

- `def extract_text(html: str) -> str` — Extract the main readable text from an HTML page.
