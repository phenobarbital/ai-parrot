---
type: Wiki Entity
title: UnderstandingHandler
id: class:parrot.handlers.understanding.UnderstandingHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: REST handler for image and video understanding.
---

# UnderstandingHandler

Defined in [`parrot.handlers.understanding`](../summaries/mod:parrot.handlers.understanding.md).

```python
class UnderstandingHandler(BaseView)
```

REST handler for image and video understanding.

Endpoints:
    POST /api/v1/google/understanding — Analyse image or video.
    GET  /api/v1/google/understanding — Return parameter catalog / JSON schema.

The POST endpoint accepts two request modes:

* **Multipart** (``multipart/form-data``): upload a file via the ``file``
  field plus a ``prompt`` text field. Optional ``media_type`` and ``model``
  fields may also be included.
* **JSON** (``application/json``): send a ``UnderstandingRequest`` payload
  with ``media_url`` pointing at a remote image or video.

Media type (image vs video) is resolved in this priority order:

1. Explicit ``media_type`` field (``'image'`` or ``'video'``).
2. ``Content-Type`` header of the uploaded file part (multipart only).
3. File extension of the uploaded filename or URL path.

## Methods

- `def setup(cls, app: Any, route: str='/api/v1/google/understanding') -> None` — Register the handler view on *app* at *route*.
- `async def post(self) -> web.Response` — Analyse one or more images (and optionally one video) and return the result.
- `async def get(self) -> web.Response` — Return the parameter catalog and JSON schema for this endpoint.
