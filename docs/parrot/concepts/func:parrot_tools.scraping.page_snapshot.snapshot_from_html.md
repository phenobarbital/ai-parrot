---
type: Concept
title: snapshot_from_html()
id: func:parrot_tools.scraping.page_snapshot.snapshot_from_html
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build a ``PageSnapshot`` from raw HTML without any network call.
---

# snapshot_from_html

```python
def snapshot_from_html(html: str) -> PageSnapshot
```

Build a ``PageSnapshot`` from raw HTML without any network call.

Args:
    html: Raw HTML document.

Returns:
    Populated ``PageSnapshot``.
