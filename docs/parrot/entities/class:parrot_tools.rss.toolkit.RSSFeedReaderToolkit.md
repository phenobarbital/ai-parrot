---
type: Wiki Entity
title: RSSFeedReaderToolkit
id: class:parrot_tools.rss.toolkit.RSSFeedReaderToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit that archives RSS feed articles to disk for later retrieval.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# RSSFeedReaderToolkit

Defined in [`parrot_tools.rss.toolkit`](../summaries/mod:parrot_tools.rss.toolkit.md).

```python
class RSSFeedReaderToolkit(AbstractToolkit)
```

Toolkit that archives RSS feed articles to disk for later retrieval.

Args:
    feeds: Feed list — plain URLs, dicts of :class:`FeedSite` fields
        (``url``, ``name``, ``max_items``, ``use_browser``), or
        ``FeedSite`` instances.
    storage_dir: Archive root. Defaults to ``OUTPUT_DIR/rss_feeds``.
    max_items_per_feed: Default cap on items processed per feed.
    concurrency: Max concurrent aiohttp requests across all feeds.
    browser_concurrency: Max concurrent Selenium fallback slots.
    min_text_length: Extracted-text length under which a page is
        considered JS-rendered and retried in the browser.
    request_timeout: Per-request timeout in seconds.
    use_browser_fallback: Disable to never launch a browser.
    browser: Selenium browser type for the fallback.
    headless: Run the fallback browser headless.

## Methods

- `async def start(self) -> None` — Create the HTTP session, semaphores, and article fetcher.
- `async def stop(self) -> None` — Close the fetcher (Selenium driver) and the HTTP session.
- `async def read_feeds(self, feed_urls: Optional[List[str]]=None, max_items: Optional[int]=None, force_refresh: bool=False) -> List[Dict[str, Any]]` — Fetch RSS feeds and archive the full content of every linked article.
- `async def get_content(self, item: str, format: str='text', max_chars: int=20000) -> Dict[str, Any]` — Retrieve the archived content of a previously fetched article.
- `async def list_feeds(self) -> List[Dict[str, Any]]` — List the RSS feeds this toolkit is configured to read.
- `async def list_saved(self, feed: Optional[str]=None, limit: int=50) -> List[Dict[str, Any]]` — List previously archived feed items, newest first.
