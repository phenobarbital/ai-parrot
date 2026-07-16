---
type: Wiki Entity
title: SiteSearchToolkit
id: class:parrot_tools.sitesearch.toolkit.SiteSearchToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for site-specific web searches with preset configurations.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# SiteSearchToolkit

Defined in [`parrot_tools.sitesearch.toolkit`](../summaries/mod:parrot_tools.sitesearch.toolkit.md).

```python
class SiteSearchToolkit(AbstractToolkit)
```

Toolkit for site-specific web searches with preset configurations.

Provides two tools:
- site_presets_list: Discover available preset configurations
- site_search: Perform site-specific searches with optional preset support

## Methods

- `async def site_presets_list(self) -> Dict[str, Any]` — List available preset configurations for site search.
- `async def site_search(self, url: str=None, query: str=None, preset: str=None, selectors: List[str]=None, max_results: int=3) -> Dict[str, Any]` — Search within a given site and return fully-rendered page content as markdown.
