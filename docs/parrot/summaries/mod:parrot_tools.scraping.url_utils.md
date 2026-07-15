---
type: Wiki Summary
title: parrot_tools.scraping.url_utils
id: mod:parrot_tools.scraping.url_utils
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: URL normalization utilities for the CrawlEngine.
relates_to:
- concept: func:parrot_tools.scraping.url_utils.normalize_url
  rel: defines
---

# `parrot_tools.scraping.url_utils`

URL normalization utilities for the CrawlEngine.

Provides consistent URL normalization for deduplication across
crawl sessions. All discovered URLs pass through normalize_url()
before being added to the visited set or frontier queue.

## Functions

- `def normalize_url(url: str, base: str='') -> Optional[str]` — Normalize a URL for deduplication.
