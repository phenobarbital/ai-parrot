---
type: Concept
title: fetch_snapshot()
id: func:parrot_tools.scraping.page_snapshot.fetch_snapshot
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Fetch a URL via ``aiohttp`` and build a ``PageSnapshot``.
---

# fetch_snapshot

```python
async def fetch_snapshot(url: str, *, timeout: float=10.0, user_agent: str=DEFAULT_UA, session: Optional[aiohttp.ClientSession]=None) -> Optional[PageSnapshot]
```

Fetch a URL via ``aiohttp`` and build a ``PageSnapshot``.

Returns ``None`` on any fetch failure — plan generation should then
fall back to an empty snapshot rather than crashing. JS-rendered
pages will produce a sparse snapshot; capture HTML via the browser
driver and call ``snapshot_from_html`` directly for those.

Args:
    url: Target URL to fetch.
    timeout: Request timeout in seconds.
    user_agent: User-Agent header.
    session: Optional pre-existing ``aiohttp.ClientSession`` to reuse.

Returns:
    A ``PageSnapshot`` or ``None`` if the fetch failed.
