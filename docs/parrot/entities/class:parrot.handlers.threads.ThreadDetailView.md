---
type: Wiki Entity
title: ThreadDetailView
id: class:parrot.handlers.threads.ThreadDetailView
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Detail operations on a single conversation thread.
---

# ThreadDetailView

Defined in [`parrot.handlers.threads`](../summaries/mod:parrot.handlers.threads.md).

```python
class ThreadDetailView(BaseView)
```

Detail operations on a single conversation thread.

GET    /api/v1/threads/{session_id}    — load turns
PATCH  /api/v1/threads/{session_id}    — update metadata
DELETE /api/v1/threads/{session_id}    — delete + cascade

## Methods

- `async def get(self) -> web.Response` — Load turns for a conversation thread.
- `async def patch(self) -> web.Response` — Update thread metadata (title, pinned, tags).
- `async def delete(self) -> web.Response` — Delete a thread and cascade-delete all artifacts.
