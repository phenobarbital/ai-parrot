---
type: Wiki Entity
title: RedisBrokerHook
id: class:parrot.core.hooks.brokers.redis.RedisBrokerHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Consumes messages from a Redis Stream.
relates_to:
- concept: class:parrot.core.hooks.brokers.base.BaseBrokerHook
  rel: extends
---

# RedisBrokerHook

Defined in [`parrot.core.hooks.brokers.redis`](../summaries/mod:parrot.core.hooks.brokers.redis.md).

```python
class RedisBrokerHook(BaseBrokerHook)
```

Consumes messages from a Redis Stream.

## Methods

- `async def connect(self) -> None`
- `async def disconnect(self) -> None`
- `async def start_consuming(self) -> None`
