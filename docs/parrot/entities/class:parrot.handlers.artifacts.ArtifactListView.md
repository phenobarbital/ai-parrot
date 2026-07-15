---
type: Wiki Entity
title: ArtifactListView
id: class:parrot.handlers.artifacts.ArtifactListView
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: List and create artifacts for a thread.
---

# ArtifactListView

Defined in [`parrot.handlers.artifacts`](../summaries/mod:parrot.handlers.artifacts.md).

```python
class ArtifactListView(BaseView)
```

List and create artifacts for a thread.

GET  /api/v1/threads/{session_id}/artifacts      — list summaries
POST /api/v1/threads/{session_id}/artifacts      — create artifact

## Methods

- `async def get(self) -> web.Response` — List all artifacts for a session as lightweight summaries.
- `async def post(self) -> web.Response` — Save a new artifact.
