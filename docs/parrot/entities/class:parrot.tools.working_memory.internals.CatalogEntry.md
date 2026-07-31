---
type: Wiki Entity
title: CatalogEntry
id: class:parrot.tools.working_memory.internals.CatalogEntry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Metadata and data container for a stored DataFrame in the catalog.
---

# CatalogEntry

Defined in [`parrot.tools.working_memory.internals`](../summaries/mod:parrot.tools.working_memory.internals.md).

```python
class CatalogEntry
```

Metadata and data container for a stored DataFrame in the catalog.

## Methods

- `def shape(self) -> tuple[int, int]` — Return the shape of the stored DataFrame.
- `def columns(self) -> list[str]` — Return column names of the stored DataFrame.
- `def dtypes_summary(self) -> dict[str, str]` — Return column dtypes as a string dictionary.
- `def compact_summary(self, max_rows: int=5, max_cols: int=20) -> dict` — Return a token-efficient summary for the LLM context.
