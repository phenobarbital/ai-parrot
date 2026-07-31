---
type: Wiki Entity
title: MetadataResult
id: class:parrot.tools.databasequery.base.MetadataResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of a metadata discovery operation.
---

# MetadataResult

Defined in [`parrot.tools.databasequery.base`](../summaries/mod:parrot.tools.databasequery.base.md).

```python
class MetadataResult(BaseModel)
```

Result of a metadata discovery operation.

Attributes:
    driver: The database driver used.
    tables: List of table/collection metadata.
    raw: Raw metadata from the database (driver-specific).
