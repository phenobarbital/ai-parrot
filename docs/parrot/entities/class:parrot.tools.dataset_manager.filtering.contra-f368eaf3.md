---
type: Wiki Entity
title: ValuesSource
id: class:parrot.tools.dataset_manager.filtering.contracts.ValuesSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Specifies where to obtain the distinct values for a frontend combo.
---

# ValuesSource

Defined in [`parrot.tools.dataset_manager.filtering.contracts`](../summaries/mod:parrot.tools.dataset_manager.filtering.contracts.md).

```python
class ValuesSource(BaseModel)
```

Specifies where to obtain the distinct values for a frontend combo.

At most one of ``query_slug``, ``column``, or ``dataset`` is typically
provided. All are optional; when present they are used by
``DatasetManager.get_filter_values`` to locate the value list.

Attributes:
    query_slug: Named query slug whose result set provides the values.
    column: Column name to run a DISTINCT query against.
    dataset: Restrict value inference to a single named dataset.
