---
type: Concept
title: community_color()
id: func:parrot.knowledge.graphindex.export_html.community_color
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the deterministic colour for a community display index.
---

# community_color

```python
def community_color(index: int) -> str
```

Return the deterministic colour for a community display index.

Args:
    index: Zero-based position of the community in display order.

Returns:
    A hex colour string. Indices beyond the palette wrap around.
