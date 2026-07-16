---
type: Wiki Entity
title: StoreRule
id: class:parrot.registry.routing.models.StoreRule
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: One heuristic rule that maps a query pattern to a preferred store.
---

# StoreRule

Defined in [`parrot.registry.routing.models`](../summaries/mod:parrot.registry.routing.models.md).

```python
class StoreRule(BaseModel)
```

One heuristic rule that maps a query pattern to a preferred store.

Args:
    pattern: Lowercase substring or regex (see ``regex`` flag).
    store: Target store type.
    weight: Confidence weight assigned when the rule fires (0–1).
    regex: When ``True``, ``pattern`` is compiled as a regular expression
        and matched via ``re.search``.  When ``False`` (default), a
        plain substring match is used.
