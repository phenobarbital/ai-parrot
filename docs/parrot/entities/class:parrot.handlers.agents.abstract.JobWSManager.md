---
type: Wiki Entity
title: JobWSManager
id: class:parrot.handlers.agents.abstract.JobWSManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extends the generic WebSocketManager with one helper that sends
---

# JobWSManager

Defined in [`parrot.handlers.agents.abstract`](../summaries/mod:parrot.handlers.agents.abstract.md).

```python
class JobWSManager(WebSocketManager)
```

Extends the generic WebSocketManager with one helper that sends
a direct message to the user owning a finished job.

## Methods

- `async def notify_job_done(self, *, user_id: int | str, job_id: str, status: str, result: Optional[Any]=None, error: Optional[str]=None) -> None` — Push a JSON message to every open WS belonging to `user_id`.
