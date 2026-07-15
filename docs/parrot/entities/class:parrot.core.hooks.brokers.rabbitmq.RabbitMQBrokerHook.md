---
type: Wiki Entity
title: RabbitMQBrokerHook
id: class:parrot.core.hooks.brokers.rabbitmq.RabbitMQBrokerHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Consumes messages from a RabbitMQ queue.
relates_to:
- concept: class:parrot.core.hooks.brokers.base.BaseBrokerHook
  rel: extends
---

# RabbitMQBrokerHook

Defined in [`parrot.core.hooks.brokers.rabbitmq`](../summaries/mod:parrot.core.hooks.brokers.rabbitmq.md).

```python
class RabbitMQBrokerHook(BaseBrokerHook)
```

Consumes messages from a RabbitMQ queue.

## Methods

- `async def connect(self) -> None`
- `async def disconnect(self) -> None`
- `async def start_consuming(self) -> None`
