---
type: Wiki Entity
title: CrawlResult
id: class:parrot_tools.scraping.crawl_graph.CrawlResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Summary of a completed crawl session.
---

# CrawlResult

Defined in [`parrot_tools.scraping.crawl_graph`](../summaries/mod:parrot_tools.scraping.crawl_graph.md).

```python
class CrawlResult
```

Summary of a completed crawl session.

Attributes:
    start_url: The seed URL that initiated the crawl.
    depth: Maximum BFS depth that was configured.
    pages: Collected page data from all successfully scraped nodes.
    visited_urls: List of all normalized URLs that were visited.
    failed_urls: List of normalized URLs that failed during scraping.
    total_pages: Count of successfully scraped pages.
    total_elapsed_seconds: Wall-clock time for the entire crawl.
    plan_used: Optional identifier of the scraping plan used.
