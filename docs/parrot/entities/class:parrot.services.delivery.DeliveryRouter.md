---
type: Wiki Entity
title: DeliveryRouter
id: class:parrot.services.delivery.DeliveryRouter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Routes task results to the appropriate delivery channel.
---

# DeliveryRouter

Defined in [`parrot.services.delivery`](../summaries/mod:parrot.services.delivery.md).

```python
class DeliveryRouter
```

Routes task results to the appropriate delivery channel.

## Methods

- `async def deliver(self, task: AgentTask, result: TaskResult) -> bool` — Deliver a task result via the configured channel.
- `async def close(self) -> None` — Close the shared HTTP session.
