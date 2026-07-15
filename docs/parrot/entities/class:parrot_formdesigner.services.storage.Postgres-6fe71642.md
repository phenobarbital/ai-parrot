---
type: Wiki Entity
title: PostgresFormStorage
id: class:parrot_formdesigner.services.storage.PostgresFormStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Persist FormSchema objects in a PostgreSQL table using asyncpg.
---

# PostgresFormStorage

Defined in [`parrot_formdesigner.services.storage`](../summaries/mod:parrot_formdesigner.services.storage.md).

```python
class PostgresFormStorage(FormStorage)
```

Persist FormSchema objects in a PostgreSQL table using asyncpg.

Supports two construction modes:

1. **Self-managed pool** (recommended): pass ``dsn`` (or connection kwargs).
   ``initialize()`` creates the pool; ``close()`` closes it.

2. **External pool** (backward compatible): pass an existing ``pool``.
   ``close()`` will NOT close an externally-provided pool.

The target schema is assumed to exist — it is NOT auto-created. Configure
per-tenant schemas at the DBA level before using a tenant override.

Args:
    pool: An existing ``asyncpg`` connection pool. When provided,
        ``_owns_pool`` is False and ``close()`` will not close it.
    dsn: asyncpg DSN string (e.g. ``"postgresql://user:pw@host/db"``).
        Used by ``initialize()`` to create the pool when ``pool`` is None.
    schema: Postgres schema where the table lives. Default
        ``"navigator"``. Used when no per-call tenant overrides it.
    table_name: Table name within ``schema``. Default ``"form_schemas"``.
    tenant: Optional default tenant slug. When set, every operation
        without an explicit ``tenant=`` kwarg targets
        ``<tenant>.<table_name>`` instead of ``<schema>.<table_name>``.
    min_size: Minimum asyncpg pool size (default 2). Ignored when pool
        is provided externally.
    max_size: Maximum asyncpg pool size (default 10). Ignored when pool
        is provided externally.
    **pool_kwargs: Additional keyword arguments forwarded to
        ``asyncpg.create_pool()`` when creating a self-managed pool.

## Methods

- `async def initialize(self, *, tenant: str | None=None) -> None` — Create the configured table if it does not exist.
- `async def close(self) -> None` — Close the asyncpg pool if this storage owns it.
- `async def save(self, form: FormSchema, style: StyleSchema | None=None, *, created_by: str | None=None, tenant: str | None=None) -> str` — Persist a FormSchema (UPSERT by form_id + version).
- `async def load(self, form_id: str, version: str | None=None, *, tenant: str | None=None) -> FormSchema | None` — Load a FormSchema from PostgreSQL.
- `async def delete(self, form_id: str, *, tenant: str | None=None) -> bool` — Delete all versions of a form from PostgreSQL.
- `async def list_forms(self, *, tenant: str | None=None) -> list[dict[str, Any]]` — List all persisted forms (latest version of each).
