---
type: Wiki Entity
title: RSSContentInterface
id: class:parrot.interfaces.rss_content.RSSContentInterface
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extends RSSInterface to fetch and summarize content from linked pages.
relates_to:
- concept: class:parrot.interfaces.rss.RSSInterface
  rel: extends
---

# RSSContentInterface

Defined in [`parrot.interfaces.rss_content`](../summaries/mod:parrot.interfaces.rss_content.md).

```python
class RSSContentInterface(RSSInterface)
```

Extends RSSInterface to fetch and summarize content from linked pages.

## Methods

- `async def read_rss_with_content(self, url: str, limit: int=10, max_chars: int=1000, output_format: str='dict', fetch_content: bool=True) -> Any` — Read RSS feed and fetch content summaries from linked pages.
