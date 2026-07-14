---
type: Concept
title: join_ids()
id: func:parrot.knowledge.ontology.tool_dispatcher.join_ids
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Join the values of a given key across a list of dicts.
---

# join_ids

```python
def join_ids(items: list[dict[str, Any]], key: str='_id', sep: str=',') -> str
```

Join the values of a given key across a list of dicts.

Args:
    items: List of dicts.
    key: Key to extract from each dict.
    sep: Separator string.

Returns:
    Joined string of extracted values.
