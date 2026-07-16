---
type: Wiki Entity
title: ArticleFetcher
id: class:parrot_tools.rss.fetcher.ArticleFetcher
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Fetches feed XML and article pages with bounded concurrency.
---

# ArticleFetcher

Defined in [`parrot_tools.rss.fetcher`](../summaries/mod:parrot_tools.rss.fetcher.md).

```python
class ArticleFetcher
```

Fetches feed XML and article pages with bounded concurrency.

Args:
    session: Shared aiohttp client session.
    http_semaphore: Bounds concurrent aiohttp requests (feeds + pages).
    browser_semaphore: Bounds concurrent Selenium fetch slots.
    min_text_length: Extracted-text length below which a page is
        considered "thin" (fallback candidate).
    request_timeout: Per-request timeout in seconds.
    selenium_config: Extra kwargs forwarded to ``SeleniumSetup``
        (e.g. ``{"browser": "chrome", "headless": True}``).
    use_browser_fallback: Master switch for the Selenium fallback.

## Methods

- `async def fetch_feed_xml(self, url: str) -> str` — Download a feed's raw XML.
- `async def parse_feed(self, xml: str) -> Any` — Parse feed XML with feedparser off the event loop.
- `async def fetch_page(self, url: str, use_browser: bool=False) -> FetchedPage` — Fetch the complete content of an article page.
- `async def close(self) -> None` — Quit the shared Selenium driver, ignoring shutdown errors.
