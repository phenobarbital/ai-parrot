---
type: Wiki Entity
title: BaseBrokerHook
id: class:parrot.core.hooks.brokers.base.BaseBrokerHook
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base for message-queue / stream broker hooks.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# BaseBrokerHook

Defined in [`parrot.core.hooks.brokers.base`](../summaries/mod:parrot.core.hooks.brokers.base.md).

```python
class BaseBrokerHook(BaseHook)
```

Abstract base for message-queue / stream broker hooks.

Subclasses implement ``connect()``, ``disconnect()``, and
``start_consuming()`` to integrate with a specific broker.

## Methods

- `async def start(self) -> None`
- `async def stop(self) -> None`
- `async def connect(self) -> None` — Establish connection to the broker.
- `async def disconnect(self) -> None` — Gracefully disconnect from the broker.
- `async def start_consuming(self) -> None` — Start consuming messages (blocking coroutine).
