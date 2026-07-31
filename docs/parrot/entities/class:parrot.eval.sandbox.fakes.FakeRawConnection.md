---
type: Wiki Entity
title: FakeRawConnection
id: class:parrot.eval.sandbox.fakes.FakeRawConnection
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Fake asyncpg connection that routes CRUD SQL to a ``DictStateBackend``.
---

# FakeRawConnection

Defined in [`parrot.eval.sandbox.fakes`](../summaries/mod:parrot.eval.sandbox.fakes.md).

```python
class FakeRawConnection
```

Fake asyncpg connection that routes CRUD SQL to a ``DictStateBackend``.

``PostgresToolkit._run_on_conn`` calls three methods on the raw
connection:
- ``await conn.execute(sql, *args)`` — no return value needed
- ``await conn.fetchrow(sql, *args)`` — returns a dict-like or None
- ``await conn.fetch(sql, *args)`` — returns a list of dict-likes

This fake parses the table name from the SQL text (the SQL templates
produced by ``PostgresToolkit`` are well-structured) and delegates to
``DictStateBackend`` CRUD operations.  It is intentionally not a
general-purpose SQL engine.

Args:
    backend: The ``DictStateBackend`` instance holding world state.

## Methods

- `async def execute(self, sql: str, *args: Any) -> None` — Execute a DML statement (INSERT / UPDATE / DELETE).
- `async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None` — Execute a query returning at most one row.
- `async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]` — Execute a query returning multiple rows.
- `async def close(self) -> None` — No-op close.
