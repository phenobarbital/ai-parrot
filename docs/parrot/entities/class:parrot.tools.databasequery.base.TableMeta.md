---
type: Wiki Entity
title: TableMeta
id: class:parrot.tools.databasequery.base.TableMeta
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Metadata for a single database table, collection, or measurement.
---

# TableMeta

Defined in [`parrot.tools.databasequery.base`](../summaries/mod:parrot.tools.databasequery.base.md).

```python
class TableMeta(BaseModel)
```

Metadata for a single database table, collection, or measurement.

Attributes:
    name: Table or collection name.
    schema_name: Schema or namespace (optional).
    columns: List of column/field metadata.
    row_count: Approximate row count (optional).
