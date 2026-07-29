---
type: Wiki Entity
title: DatasetFilterHandler
id: class:parrot.handlers.dataset_filter_handler.DatasetFilterHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: aiohttp handler for common-field filter endpoints.
---

# DatasetFilterHandler

Defined in [`parrot.handlers.dataset_filter_handler`](../summaries/mod:parrot.handlers.dataset_filter_handler.md).

```python
class DatasetFilterHandler
```

aiohttp handler for common-field filter endpoints.

Endpoints:
    GET  /api/v1/filters/{agent_id}/schema          — filter catalog
    GET  /api/v1/filters/{agent_id}/values/{name}   — distinct values
    POST /api/v1/filters/{agent_id}                  — apply filters

Note: This handler is designed to be imported and mounted by the
``ai-parrot-server`` package.  It does not inherit from ``BaseView``
directly to keep the core ``ai-parrot`` package server-independent.

## Methods

- `async def get(self) -> web.Response` — Handle GET requests.
- `async def post(self) -> web.Response` — POST .../filters/{agent_id} — apply a filter request.
