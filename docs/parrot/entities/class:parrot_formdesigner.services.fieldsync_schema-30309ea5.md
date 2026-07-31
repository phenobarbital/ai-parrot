---
type: Wiki Entity
title: FieldsyncSchemaManager
id: class:parrot_formdesigner.services.fieldsync_schema.FieldsyncSchemaManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Apply the canonical ``fieldsync`` DDL to a Postgres database.
---

# FieldsyncSchemaManager

Defined in [`parrot_formdesigner.services.fieldsync_schema`](../summaries/mod:parrot_formdesigner.services.fieldsync_schema.md).

```python
class FieldsyncSchemaManager
```

Apply the canonical ``fieldsync`` DDL to a Postgres database.

All DDL statements are idempotent — executing ``initialize()`` twice on
the same database is safe and produces no side effects.

This class never opens a connection itself; it receives an existing
asyncpg pool (or a compatible fake pool for unit tests).

Args:
    pool: asyncpg connection pool (or fake with the same ``acquire()``
        async context manager interface).

Example::

    pool = await asyncpg.create_pool(dsn=DB_DSN)
    mgr = FieldsyncSchemaManager(pool)
    await mgr.initialize()

## Methods

- `async def initialize(self) -> None` — Run all DDL statements in order, creating schema + 3 tables.
- `def ddl_statements() -> list[str]` — Return the ordered list of DDL SQL strings (read-only copy).
