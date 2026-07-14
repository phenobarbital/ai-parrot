---
type: Wiki Entity
title: PostgresFormStorage
id: class:parrot.forms.storage.PostgresFormStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Persist FormSchema objects in a PostgreSQL table using asyncpg.
---

# PostgresFormStorage

Defined in [`parrot.forms.storage`](../summaries/mod:parrot.forms.storage.md).

```python
class PostgresFormStorage(FormStorage)
```

Persist FormSchema objects in a PostgreSQL table using asyncpg.

Requires `asyncpg` to be installed. The database pool is passed in
at construction time (no internal connection management).

Table name: form_schemas (created via initialize()).

Example:
    pool = await asyncpg.create_pool(dsn="postgresql://user:pw@host/db")
    storage = PostgresFormStorage(pool=pool)
    await storage.initialize()

    await storage.save(form)
    form = await storage.load("my-form")
    forms = await storage.list_forms()
    await storage.delete("my-form")

## Methods

- `async def initialize(self) -> None` — Create the form_schemas table if it does not exist.
- `async def close(self) -> None` — Close the asyncpg pool if this storage owns it.
- `async def save(self, form: FormSchema, style: StyleSchema | None=None, *, created_by: str | None=None) -> str` — Persist a FormSchema (UPSERT by form_id + version).
- `async def load(self, form_id: str, version: str | None=None) -> FormSchema | None` — Load a FormSchema from PostgreSQL.
- `async def delete(self, form_id: str) -> bool` — Delete all versions of a form from PostgreSQL.
- `async def list_forms(self) -> list[dict[str, str]]` — List all persisted forms (latest version of each).
