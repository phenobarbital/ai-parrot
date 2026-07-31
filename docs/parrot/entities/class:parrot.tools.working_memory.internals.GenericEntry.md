---
type: Wiki Entity
title: GenericEntry
id: class:parrot.tools.working_memory.internals.GenericEntry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Catalog entry for non-DataFrame data.
---

# GenericEntry

Defined in [`parrot.tools.working_memory.internals`](../summaries/mod:parrot.tools.working_memory.internals.md).

```python
class GenericEntry
```

Catalog entry for non-DataFrame data.

Stores arbitrary Python objects alongside type-specific metadata
and provides a type-aware compact summary for the LLM context.

Attributes:
    key: Unique identifier in the working memory catalog.
    data: The stored Python object (any type).
    entry_type: Discriminator describing the kind of data.
    created_at: Unix timestamp when this entry was created.
    description: Optional human-readable description.
    turn_id: Optional conversation turn identifier.
    session_id: Optional session identifier.
    metadata: Optional arbitrary user-defined metadata dict.

## Methods

- `def compact_summary(self, max_length: int=500) -> dict` — Return a type-aware compact summary suitable for the LLM context.
