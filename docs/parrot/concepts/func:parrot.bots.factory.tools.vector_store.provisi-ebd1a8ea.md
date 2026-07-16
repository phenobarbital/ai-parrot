---
type: Concept
title: provision_vector_store()
id: func:parrot.bots.factory.tools.vector_store.provision_vector_store
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create a PgVector table and return a ``StoreConfig``-shaped dict.
---

# provision_vector_store

```python
async def provision_vector_store(table: str, *, schema: str='public', dimension: int=768, embedding_model: str='sentence-transformers/all-mpnet-base-v2', extra_columns: Optional[List[str]]=None, dsn: Optional[str]=None) -> Dict[str, Any]
```

Create a PgVector table and return a ``StoreConfig``-shaped dict.

Args:
    table: Target table name.
    schema: Postgres schema (defaults to ``public``).
    dimension: Embedding vector dimension. Match it to ``embedding_model``.
    embedding_model: HuggingFace / sentence-transformers identifier.
    extra_columns: Additional non-vector columns to add to the table.
    dsn: Optional Postgres DSN override; falls back to PgVector defaults
        (driven by env vars: ``PG_HOST``, ``PG_USER``, …).

Returns:
    Dict with ``provider``, ``table``, ``schema``, ``dimension``,
    ``embedding_model`` ready to use as the ``vector_store`` block of an
    ``AgentDefinition``.
