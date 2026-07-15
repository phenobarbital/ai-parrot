---
type: Wiki Summary
title: parrot_tools.scraping.link_discoverer
id: mod:parrot_tools.scraping.link_discoverer
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Link discovery for the CrawlEngine.
relates_to:
- concept: class:parrot_tools.scraping.link_discoverer.LinkDiscoverer
  rel: defines
- concept: mod:parrot_tools.scraping.url_utils
  rel: references
---

# `parrot_tools.scraping.link_discoverer`

Link discovery for the CrawlEngine.

Extracts and filters links from HTML content, applying domain scoping,
URL pattern filtering, and depth guards before returning normalized URLs.

## Classes

- **`LinkDiscoverer`** — Discovers and filters links from HTML pages.
