---
type: Wiki Entity
title: CrawlEngine
id: class:parrot_tools.scraping.crawler.CrawlEngine
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestrates multi-page crawling.
---

# CrawlEngine

Defined in [`parrot_tools.scraping.crawler`](../summaries/mod:parrot_tools.scraping.crawler.md).

```python
class CrawlEngine
```

Orchestrates multi-page crawling.

Delegates:
  - Page execution  -> ``scrape_fn`` callable (provided by the toolkit)
  - Link discovery  -> ``LinkDiscoverer``
  - Traversal order -> ``CrawlStrategy``

Args:
    scrape_fn: Async callable ``(url, plan) -> result`` that scrapes a
        single page. The result object must expose a ``raw_html`` attribute
        (or similar) for link discovery.
    strategy: Traversal strategy; defaults to ``BFSStrategy``.
    follow_selector: Default CSS selector for link elements.
    follow_pattern: Default regex pattern to filter discovered URLs.
    allow_external: Whether to follow links outside the start domain.
    concurrency: Number of concurrent page scrapes. ``1`` (default) is
        safe for all drivers; higher values require concurrent-capable
        drivers.
    logger: Optional logger; one is created if not provided.

## Methods

- `async def run(self, start_url: str, plan: Any, depth: int=1, max_pages: Optional[int]=None) -> CrawlResult` — Execute the crawl and return aggregated results.
