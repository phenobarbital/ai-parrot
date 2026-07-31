---
type: Wiki Entity
title: PostgresListenHook
id: class:parrot.core.hooks.postgres.PostgresListenHook
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Listens to a PostgreSQL channel via LISTEN/NOTIFY and emits HookEvents.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# PostgresListenHook

Defined in [`parrot.core.hooks.postgres`](../summaries/mod:parrot.core.hooks.postgres.md).

```python
class PostgresListenHook(BaseHook)
```

Listens to a PostgreSQL channel via LISTEN/NOTIFY and emits HookEvents.

## Methods

- `async def start(self) -> None`
- `async def stop(self) -> None`
