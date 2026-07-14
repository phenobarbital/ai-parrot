---
type: Wiki Entity
title: VectorStoreHandler
id: class:parrot.handlers.stores.handler.VectorStoreHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST API for vector store lifecycle management.
---

# VectorStoreHandler

Defined in [`parrot.handlers.stores.handler`](../summaries/mod:parrot.handlers.stores.handler.md).

```python
class VectorStoreHandler(BaseView)
```

REST API for vector store lifecycle management.

Endpoints:
    POST  /api/v1/ai/stores             — create/prepare collection
    PUT   /api/v1/ai/stores             — load data into collection
    PATCH /api/v1/ai/stores             — test search
    GET   /api/v1/ai/stores             — metadata (unauthenticated delegate)
    GET   /api/v1/ai/stores/jobs/{job_id} — job status

## Methods

- `def post_init(self, *args, **kwargs)` — Initialise logger on handler construction.
- `def setup(cls, app: web.Application) -> None` — Register routes and lifecycle hooks.
- `async def get(self) -> web.Response` — Handle GET requests.
- `async def post(self) -> web.Response` — Create or prepare a vector store collection.
- `async def patch(self) -> web.Response` — Test search against a vector store collection.
- `async def put(self) -> web.Response` — Load data into a vector store collection.
