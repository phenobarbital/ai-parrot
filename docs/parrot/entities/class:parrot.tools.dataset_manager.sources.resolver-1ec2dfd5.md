---
type: Wiki Entity
title: PhysicalResources
id: class:parrot.tools.dataset_manager.sources.resolver.PhysicalResources
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Resolved physical resources for a DataSource.
---

# PhysicalResources

Defined in [`parrot.tools.dataset_manager.sources.resolver`](../summaries/mod:parrot.tools.dataset_manager.sources.resolver.md).

```python
class PhysicalResources(BaseModel)
```

Resolved physical resources for a DataSource.

Attributes:
    driver: Canonical driver name (e.g. ``"bigquery"``, ``"pg"``).
    tables: Set of table resource strings in ``"driver:schema.table"``
        form, used as resource IDs in the PBAC engine
        (``table:<driver>:<schema>.<table>``).
    source_type: Non-SQL source type identifier (e.g. ``"mongo"``).
    source_id: Non-SQL source identifier (e.g. ``"finance_db.transactions"``).
