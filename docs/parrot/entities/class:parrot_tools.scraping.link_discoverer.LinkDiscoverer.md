---
type: Wiki Entity
title: LinkDiscoverer
id: class:parrot_tools.scraping.link_discoverer.LinkDiscoverer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Discovers and filters links from HTML pages.
---

# LinkDiscoverer

Defined in [`parrot_tools.scraping.link_discoverer`](../summaries/mod:parrot_tools.scraping.link_discoverer.md).

```python
class LinkDiscoverer
```

Discovers and filters links from HTML pages.

Extracts URLs from HTML elements matching a CSS selector, normalizes
them, and applies domain scoping and regex pattern filters.

Args:
    follow_selector: CSS selector for elements to extract links from.
    follow_pattern: Optional regex pattern; only URLs matching it are kept.
    base_domain: If set, restricts discovered URLs to this domain
        (unless allow_external is True).
    allow_external: When False (default), URLs outside base_domain
        are discarded.

## Methods

- `def discover(self, html: str, base_url: str, current_depth: int, max_depth: int) -> List[str]` — Extract, normalize, and filter links from *html*.
