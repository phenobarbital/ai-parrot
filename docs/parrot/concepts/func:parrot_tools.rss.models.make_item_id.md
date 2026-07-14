---
type: Concept
title: make_item_id()
id: func:parrot_tools.rss.models.make_item_id
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Derive a stable item identifier from an article link.
---

# make_item_id

```python
def make_item_id(link: str) -> str
```

Derive a stable item identifier from an article link.

Args:
    link: Article URL as found in the feed entry.

Returns:
    First 16 hex chars of the SHA-256 digest of the link.
