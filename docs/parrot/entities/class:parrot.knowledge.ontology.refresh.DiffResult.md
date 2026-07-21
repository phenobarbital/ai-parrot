---
type: Wiki Entity
title: DiffResult
id: class:parrot.knowledge.ontology.refresh.DiffResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of computing delta between new and existing data.
---

# DiffResult

Defined in [`parrot.knowledge.ontology.refresh`](../summaries/mod:parrot.knowledge.ontology.refresh.md).

```python
class DiffResult(BaseModel)
```

Result of computing delta between new and existing data.

Args:
    to_add: Records present in new data but not existing.
    to_update: Records present in both but with changed values.
    to_remove: Records present in existing but not in new data.
