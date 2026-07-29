---
type: Wiki Entity
title: WebLoader
id: class:parrot_loaders.web.WebLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Load web pages and extract HTML + Markdown + structured bits (videos/nav/tables).
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# WebLoader

Defined in [`parrot_loaders.web`](../summaries/mod:parrot_loaders.web.md).

```python
class WebLoader(AbstractLoader)
```

Load web pages and extract HTML + Markdown + structured bits (videos/nav/tables).

## Methods

- `async def open(self)` — Initialize resources - called by AbstractLoader's __aenter__.
- `async def close(self)` — Clean up resources - called by AbstractLoader's __aexit__.
- `def md(self, soup: BeautifulSoup, **options) -> str` — Convert BeautifulSoup to Markdown.
- `def clean_html(self, html: str, tags: List[str], objects: List[Dict[str, Dict[str, Any]]]=[], *, parse_videos: bool=True, parse_navs: bool=True, parse_tables: bool=True) -> Tuple[List[str], str, str]` — Clean and extract content from HTML.
