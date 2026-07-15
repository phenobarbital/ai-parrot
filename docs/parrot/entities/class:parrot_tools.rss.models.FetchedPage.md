---
type: Wiki Entity
title: FetchedPage
id: class:parrot_tools.rss.models.FetchedPage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Internal result of a single article-page fetch attempt.
---

# FetchedPage

Defined in [`parrot_tools.rss.models`](../summaries/mod:parrot_tools.rss.models.md).

```python
class FetchedPage
```

Internal result of a single article-page fetch attempt.

Attributes:
    html: Raw page HTML ('' when nothing was retrieved).
    text: Extracted main text ('' when extraction produced nothing).
    method: Mechanism that produced the html.
    status_code: HTTP status code (aiohttp path only).
    error: Error message when the fetch failed or degraded.
    thin: True when the extracted text is below the minimum length.
