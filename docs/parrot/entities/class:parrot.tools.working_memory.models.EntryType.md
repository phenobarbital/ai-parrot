---
type: Wiki Entity
title: EntryType
id: class:parrot.tools.working_memory.models.EntryType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Discriminator for catalog entry types.
---

# EntryType

Defined in [`parrot.tools.working_memory.models`](../summaries/mod:parrot.tools.working_memory.models.md).

```python
class EntryType(str, Enum)
```

Discriminator for catalog entry types.

Used by GenericEntry to describe the kind of data stored.
DATAFRAME is reserved for backward-compatible CatalogEntry summaries.
