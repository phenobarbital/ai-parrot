---
type: Wiki Entity
title: RSSInterface
id: class:parrot.interfaces.rss.RSSInterface
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: RSSInterface.
relates_to:
- concept: class:parrot.interfaces.http.HTTPService
  rel: extends
---

# RSSInterface

Defined in [`parrot.interfaces.rss`](../summaries/mod:parrot.interfaces.rss.md).

```python
class RSSInterface(HTTPService)
```

RSSInterface.

Interface for reading and parsing RSS/Atom feeds.

## Methods

- `async def read_rss(self, url: str, limit: int=10, output_format: str='dict') -> Any` — Reads an RSS feed from a URL and returns parsed items.
