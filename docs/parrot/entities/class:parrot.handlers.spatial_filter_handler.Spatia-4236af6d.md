---
type: Wiki Entity
title: SpatialFilterHandler
id: class:parrot.handlers.spatial_filter_handler.SpatialFilterHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: aiohttp handler for spatial filter endpoints.
---

# SpatialFilterHandler

Defined in [`parrot.handlers.spatial_filter_handler`](../summaries/mod:parrot.handlers.spatial_filter_handler.md).

```python
class SpatialFilterHandler
```

aiohttp handler for spatial filter endpoints.

Endpoints:
    POST /api/v1/spatial/{agent_id}/direct    — deterministic path
    POST /api/v1/spatial/{agent_id}/nl        — NL→spec synthesis path
    GET  /api/v1/spatial/{agent_id}/manifest  — dataset manifest

Both POST endpoints return the same ``SpatialFeatureCollection`` JSON
so the frontend is mode-agnostic (spec G1).

Note: This handler is designed to be imported and mounted by the
``ai-parrot-server`` package.  It does not inherit from ``BaseView``
directly to keep the core ``ai-parrot`` package server-independent;
the server package wraps it as needed.

## Methods

- `async def post(self) -> web.Response` — Handle POST requests for both direct and NL→spec paths.
- `async def get(self) -> web.Response` — GET /api/v1/spatial/{agent_id}/manifest — spatial dataset manifest.
