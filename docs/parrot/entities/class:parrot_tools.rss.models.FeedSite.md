---
type: Wiki Entity
title: FeedSite
id: class:parrot_tools.rss.models.FeedSite
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A configured RSS/Atom feed source.
---

# FeedSite

Defined in [`parrot_tools.rss.models`](../summaries/mod:parrot_tools.rss.models.md).

```python
class FeedSite(BaseModel)
```

A configured RSS/Atom feed source.

Attributes:
    url: Feed URL (RSS or Atom XML endpoint).
    name: Optional human-friendly name; used to derive the storage slug.
    max_items: Optional per-site cap on items processed per read.
    use_browser: When True, article pages for this site are always
        fetched with the Selenium browser instead of aiohttp.

## Methods

- `def from_config(cls, item: Union[str, Dict[str, Any], 'FeedSite']) -> 'FeedSite'` — Coerce a feed configuration entry into a :class:`FeedSite`.
- `def slug(self) -> str` — Filesystem-safe identifier for this feed (name or URL host+path).
