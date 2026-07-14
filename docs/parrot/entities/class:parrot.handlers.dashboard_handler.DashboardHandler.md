---
type: Wiki Entity
title: DashboardHandler
id: class:parrot.handlers.dashboard_handler.DashboardHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST API Handler for Dashboard CRUD operations.
---

# DashboardHandler

Defined in [`parrot.handlers.dashboard_handler`](../summaries/mod:parrot.handlers.dashboard_handler.md).

```python
class DashboardHandler(BaseView)
```

REST API Handler for Dashboard CRUD operations.

## Methods

- `async def get(self) -> web.Response` — GET handler.
- `async def post(self) -> web.Response` — Create a new dashboard.
- `async def put(self) -> web.Response` — Full update of an existing dashboard.
- `async def patch(self) -> web.Response` — Partially update fields on a dashboard.
- `async def delete(self) -> web.Response` — Delete a dashboard and all its tabs.
