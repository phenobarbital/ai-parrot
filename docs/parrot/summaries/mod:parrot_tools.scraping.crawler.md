---
type: Wiki Summary
title: parrot_tools.scraping.crawler
id: mod:parrot_tools.scraping.crawler
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CrawlEngine — multi-page crawl orchestrator for the WebScrapingToolkit.
relates_to:
- concept: class:parrot_tools.scraping.crawler.CrawlEngine
  rel: defines
- concept: mod:parrot_tools.scraping.crawl_graph
  rel: references
- concept: mod:parrot_tools.scraping.crawl_strategy
  rel: references
- concept: mod:parrot_tools.scraping.link_discoverer
  rel: references
---

# `parrot_tools.scraping.crawler`

CrawlEngine — multi-page crawl orchestrator for the WebScrapingToolkit.

Coordinates ``CrawlGraph`` (state), ``CrawlStrategy`` (traversal order),
``LinkDiscoverer`` (link extraction), and a caller-provided ``scrape_fn``
(page execution) to perform breadth-first or depth-first crawls across
multiple pages.

This module is not exposed as a standalone tool; the public interface is
``WebScrapingToolkit.crawl()``.

## Classes

- **`CrawlEngine`** — Orchestrates multi-page crawling.
