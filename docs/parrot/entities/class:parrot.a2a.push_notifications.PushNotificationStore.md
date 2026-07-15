---
type: Wiki Entity
title: PushNotificationStore
id: class:parrot.a2a.push_notifications.PushNotificationStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-memory store for :class:`TaskPushNotificationConfig` objects.
---

# PushNotificationStore

Defined in [`parrot.a2a.push_notifications`](../summaries/mod:parrot.a2a.push_notifications.md).

```python
class PushNotificationStore
```

In-memory store for :class:`TaskPushNotificationConfig` objects.

The backend is a per-process ``dict`` keyed by ``task_id`` then ``config_id``.
This mirrors the server's in-memory task store; a Redis-backed
implementation with the same async interface is a follow-up.

## Methods

- `async def create(self, config: TaskPushNotificationConfig) -> TaskPushNotificationConfig` — Store a push-notification config, assigning an id when absent.
- `async def get(self, task_id: str, config_id: str) -> Optional[TaskPushNotificationConfig]` — Return the config for ``(task_id, config_id)`` or ``None``.
- `async def list_for_task(self, task_id: str) -> List[TaskPushNotificationConfig]` — Return all configs registered for ``task_id``.
- `async def delete(self, task_id: str, config_id: str) -> bool` — Remove a config; return ``True`` if one was removed.
