---
type: Wiki Entity
title: PostgresResultStorage
id: class:parrot.bots.flows.core.storage.backends.postgres.PostgresResultStorage
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persist crew/flow execution results to Postgres (one row per execution).
relates_to:
- concept: class:parrot.bots.flows.core.storage.backends.base.ResultStorage
  rel: extends
---

# PostgresResultStorage

Defined in [`parrot.bots.flows.core.storage.backends.postgres`](../summaries/mod:parrot.bots.flows.core.storage.backends.postgres.md).

```python
class PostgresResultStorage(ResultStorage)
```

Persist crew/flow execution results to Postgres (one row per execution).

On first ``save()`` per table the backend issues idempotent DDL
(``CREATE TABLE IF NOT EXISTS`` + two indexes). Subsequent saves for the
same table skip the DDL (in-process cache on ``self._initialised``).

The ``collection`` argument selects the table name and is validated
against ``^[a-z_][a-z0-9_]*$`` before any SQL is issued to prevent
injection.

## Methods

- `async def save(self, collection: str, document: dict[str, Any]) -> None` — Insert one execution record into the target table.
- `async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]` — Return all rows in *collection* whose ``execution_id`` matches.
- `async def close(self) -> None` — Release the Postgres connection. Safe to call multiple times.
- `async def list(self, collection: str, filters: Optional[dict[str, Any]]=None, limit: int=20, offset: int=0) -> list[dict[str, Any]]` — List execution documents ordered by ``timestamp DESC``.
- `async def get(self, collection: str, record_id: str) -> Optional[dict[str, Any]]` — Retrieve a single execution document by its record id.
- `async def delete(self, collection: str, record_id: str) -> bool` — Delete a single execution document by its record id.
- `async def count(self, collection: str, filters: Optional[dict[str, Any]]=None) -> int` — Count execution documents matching the given filters.
