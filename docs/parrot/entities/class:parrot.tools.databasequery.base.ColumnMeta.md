---
type: Wiki Entity
title: ColumnMeta
id: class:parrot.tools.databasequery.base.ColumnMeta
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Metadata for a single database column or field.
---

# ColumnMeta

Defined in [`parrot.tools.databasequery.base`](../summaries/mod:parrot.tools.databasequery.base.md).

```python
class ColumnMeta(BaseModel)
```

Metadata for a single database column or field.

Attributes:
    name: Column name.
    data_type: Column data type.
    nullable: Whether the column allows null values.
    primary_key: Whether this column is part of the primary key.
    default: Default value for the column.
