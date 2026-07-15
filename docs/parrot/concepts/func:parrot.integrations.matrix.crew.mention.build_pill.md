---
type: Concept
title: build_pill()
id: func:parrot.integrations.matrix.crew.mention.build_pill
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build a Matrix "pill" HTML mention link.
---

# build_pill

```python
def build_pill(mxid: str, display_name: str) -> str
```

Build a Matrix "pill" HTML mention link.

Produces a clickable user mention compatible with Matrix clients that
support rich text (formatted_body).

Args:
    mxid: Full Matrix ID (e.g. ``"@analyst:example.com"``).
    display_name: Display name shown inside the pill link.

Returns:
    HTML anchor element, e.g.
    ``'<a href="https://matrix.to/#/@analyst:example.com">Financial Analyst</a>'``
