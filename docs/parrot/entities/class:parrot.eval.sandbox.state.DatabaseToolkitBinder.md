---
type: Wiki Entity
title: DatabaseToolkitBinder
id: class:parrot.eval.sandbox.state.DatabaseToolkitBinder
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Binder for ``DatabaseToolkit`` (``PostgresToolkit``) subclasses.
relates_to:
- concept: class:parrot.eval.sandbox.state.ToolkitBinder
  rel: extends
---

# DatabaseToolkitBinder

Defined in [`parrot.eval.sandbox.state`](../summaries/mod:parrot.eval.sandbox.state.md).

```python
class DatabaseToolkitBinder(ToolkitBinder)
```

Binder for ``DatabaseToolkit`` (``PostgresToolkit``) subclasses.

Sets ``toolkit._connected = True`` to bypass ``start()`` and patches
``toolkit._acquire_asyncdb_connection`` to yield a ``FakeRawConnection``
backed by the ``DictStateBackend``.  Also patches ``toolkit._resolve_table``
to return a minimal ``TableMetadata`` stub so CRUD method internals work
without a warm metadata cache.

The net effect: CRUD tool calls (``insert_row``, ``update_row``, …) go
through the full ``PostgresToolkit`` parameter-binding pipeline but the
final SQL is routed to ``FakeRawConnection`` → ``DictStateBackend`` with
NO real database connection.

## Methods

- `def bind(self, toolkit: Any, backend: 'DictStateBackend') -> None` — Inject *backend* into *toolkit*.
