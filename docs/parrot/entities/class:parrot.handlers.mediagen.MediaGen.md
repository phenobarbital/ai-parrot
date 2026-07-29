---
type: Wiki Entity
title: MediaGen
id: class:parrot.handlers.mediagen.MediaGen
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: REST handler for image and video generation.
---

# MediaGen

Defined in [`parrot.handlers.mediagen`](../summaries/mod:parrot.handlers.mediagen.md).

```python
class MediaGen(BaseView)
```

REST handler for image and video generation.

Endpoints:
    POST /api/v1/google/media — Generate images or videos.

## Methods

- `def setup(cls, app: Any, route: str='/api/v1/google/media') -> None` — Register the handler view on *app* at *route*.
- `async def post(self) -> web.Response` — Expose image and video generation endpoints in single or batch modes.
