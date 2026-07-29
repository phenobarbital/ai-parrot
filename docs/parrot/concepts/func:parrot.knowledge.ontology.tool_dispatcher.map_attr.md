---
type: Concept
title: map_attr()
id: func:parrot.knowledge.ontology.tool_dispatcher.map_attr
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract a single attribute from each dict in a list.
---

# map_attr

```python
def map_attr(items: list[dict[str, Any]], key: str) -> list[Any]
```

Extract a single attribute from each dict in a list.

Args:
    items: List of dicts.
    key: Attribute key to extract.

Returns:
    List of extracted values (``None`` for missing keys).
