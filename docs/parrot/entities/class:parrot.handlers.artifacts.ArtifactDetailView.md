---
type: Wiki Entity
title: ArtifactDetailView
id: class:parrot.handlers.artifacts.ArtifactDetailView
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Detail operations on a single artifact.
---

# ArtifactDetailView

Defined in [`parrot.handlers.artifacts`](../summaries/mod:parrot.handlers.artifacts.md).

```python
class ArtifactDetailView(BaseView)
```

Detail operations on a single artifact.

GET    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — get
PUT    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — update
DELETE /api/v1/threads/{session_id}/artifacts/{artifact_id}  — delete

## Methods

- `async def get(self) -> web.Response` — Get a single artifact with full definition resolved.
- `async def put(self) -> web.Response` — Update an artifact's definition.
- `async def delete(self) -> web.Response` — Delete an artifact and clean up S3 data.
