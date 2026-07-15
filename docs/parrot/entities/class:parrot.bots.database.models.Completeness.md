---
type: Wiki Entity
title: Completeness
id: class:parrot.bots.database.models.Completeness
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Completeness level of a cached TableMetadata entry.
---

# Completeness

Defined in [`parrot.bots.database.models`](../summaries/mod:parrot.bots.database.models.md).

```python
class Completeness(IntEnum)
```

Completeness level of a cached TableMetadata entry.

Ordered so ``meta.completeness >= required`` is the canonical check
(higher value = strictly subsumes lower levels).
