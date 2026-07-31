---
type: Wiki Entity
title: FakeTableMetadata
id: class:parrot.eval.sandbox.fakes.FakeTableMetadata
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Minimal table metadata stub used by ``DatabaseToolkitBinder``.
---

# FakeTableMetadata

Defined in [`parrot.eval.sandbox.fakes`](../summaries/mod:parrot.eval.sandbox.fakes.md).

```python
class FakeTableMetadata
```

Minimal table metadata stub used by ``DatabaseToolkitBinder``.

Provides the attributes read by ``PostgresToolkit`` internals
(``schema``, ``tablename``, ``full_name``, ``columns``,
``primary_keys``) without importing ``parrot.bots.database.models``.

Attributes:
    schema: Schema name.
    tablename: Table name.
    full_name: ``schema.tablename`` composite.
    table_type: Always ``"BASE TABLE"`` for the fake.
    columns: Empty list (CRUD pipeline skips unknown columns).
    primary_keys: Empty list.
