---
type: Wiki Entity
title: ThreadListView
id: class:parrot.handlers.threads.ThreadListView
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: List and create conversation threads.
---

# ThreadListView

Defined in [`parrot.handlers.threads`](../summaries/mod:parrot.handlers.threads.md).

```python
class ThreadListView(BaseView)
```

List and create conversation threads.

GET  /api/v1/threads?agent_id=X&limit=N  — list threads
POST /api/v1/threads                      — create thread

## Methods

- `async def get(self) -> web.Response` — List conversation threads for the authenticated user.
- `async def post(self) -> web.Response` — Create a new conversation thread.
