---
type: Wiki Entity
title: DatabaseLoader
id: class:parrot_loaders.database.DatabaseLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Load rows from a database table as RAG Documents.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# DatabaseLoader

Defined in [`parrot_loaders.database`](../summaries/mod:parrot_loaders.database.md).

```python
class DatabaseLoader(AbstractLoader)
```

Load rows from a database table as RAG Documents.

Each row becomes a single Document whose ``page_content`` is a YAML or JSON
representation of the row (minus excluded columns), and whose ``metadata``
carries table, schema, row index, source, and driver information.

Args:
    table: Table name (required).
    schema: Database schema. Defaults to ``'public'``.
    driver: AsyncDB driver name. Defaults to ``'pg'`` (PostgreSQL).
    dsn: Connection DSN string. Defaults to ``parrot.conf.default_dsn``.
    params: Alternative connection params dict (mutually exclusive with dsn).
    where: Optional SQL WHERE clause (without the ``WHERE`` keyword).
    content_format: Serialization format for ``page_content``.
        ``'yaml'`` (default) or ``'json'``.
    exclude_columns: Column names to drop from content.
        Defaults to ``['created_at', 'updated_at', 'inserted_at']``.
    **kwargs: Passed to ``AbstractLoader.__init__``.

Example::

    loader = DatabaseLoader(table='plans', schema='att')
    docs = await loader.load()

    loader = DatabaseLoader(
        table='plans',
        schema='att',
        where="plan_name NOT LIKE '%Online Only%'",
        content_format='json',
    )
    docs = await loader.load()

## Methods

- `async def load(self, source=None, **kwargs) -> List[Document]` — Load documents from the database table.
