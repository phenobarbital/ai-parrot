---
type: Wiki Entity
title: VideoReelHandler
id: class:parrot.handlers.video_reel.VideoReelHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: REST handler for video reel generation using background jobs.
---

# VideoReelHandler

Defined in [`parrot.handlers.video_reel`](../summaries/mod:parrot.handlers.video_reel.md).

```python
class VideoReelHandler(BaseView)
```

REST handler for video reel generation using background jobs.

Endpoints:
    POST /api/v1/google/generation/video_reel — Submit a video reel job (returns 202 + job_id).
    GET  /api/v1/google/generation/video_reel?job_id=<id> — Poll job status/result.
    GET  /api/v1/google/generation/video_reel — JSON Schema catalog (no job_id).

## Methods

- `def setup(cls, app: WebApp, route: str='/api/v1/google/generation/video_reel')` — Register routes and ensure JobManager is available.
- `def job_manager(self) -> JobManager` — Resolve JobManager lazily from the request's app.
- `async def post(self) -> web.Response` — Submit a video reel generation job and return immediately.
- `async def get(self) -> web.Response` — Return job status/result when job_id is provided, otherwise the schema catalog.
