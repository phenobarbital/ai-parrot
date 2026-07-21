---
type: Wiki Entity
title: UpsertResult
id: class:parrot.knowledge.ontology.graph_store.UpsertResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of a batch upsert operation.
---

# UpsertResult

Defined in [`parrot.knowledge.ontology.graph_store`](../summaries/mod:parrot.knowledge.ontology.graph_store.md).

```python
class UpsertResult(BaseModel)
```

Result of a batch upsert operation.

Args:
    inserted: Number of new nodes inserted.
    updated: Number of existing nodes updated.
    unchanged: Number of nodes that were identical (no-op).
