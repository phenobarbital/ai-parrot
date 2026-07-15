---
type: Wiki Entity
title: SQSBrokerHook
id: class:parrot.core.hooks.brokers.sqs.SQSBrokerHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Consumes messages from an AWS SQS queue.
relates_to:
- concept: class:parrot.core.hooks.brokers.base.BaseBrokerHook
  rel: extends
---

# SQSBrokerHook

Defined in [`parrot.core.hooks.brokers.sqs`](../summaries/mod:parrot.core.hooks.brokers.sqs.md).

```python
class SQSBrokerHook(BaseBrokerHook)
```

Consumes messages from an AWS SQS queue.

## Methods

- `async def connect(self) -> None`
- `async def disconnect(self) -> None`
- `async def start_consuming(self) -> None`
