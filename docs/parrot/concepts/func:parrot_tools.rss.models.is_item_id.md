---
type: Concept
title: is_item_id()
id: func:parrot_tools.rss.models.is_item_id
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Check whether a string looks like an item id produced by :func:`make_item_id`.
---

# is_item_id

```python
def is_item_id(value: str) -> bool
```

Check whether a string looks like an item id produced by :func:`make_item_id`.

Args:
    value: Candidate string.

Returns:
    True when the value is exactly 16 lowercase hex characters.
