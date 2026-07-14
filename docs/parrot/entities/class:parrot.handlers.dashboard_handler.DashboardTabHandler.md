---
type: Wiki Entity
title: DashboardTabHandler
id: class:parrot.handlers.dashboard_handler.DashboardTabHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST API Handler for Dashboard Tab CRUD operations.
---

# DashboardTabHandler

Defined in [`parrot.handlers.dashboard_handler`](../summaries/mod:parrot.handlers.dashboard_handler.md).

```python
class DashboardTabHandler(BaseView)
```

REST API Handler for Dashboard Tab CRUD operations.

## Methods

- `async def get(self) -> web.Response` — GET handler.
- `async def post(self) -> web.Response` — Create a new tab for a dashboard.
- `async def put(self) -> web.Response` — Full update of an existing tab.
- `async def patch(self) -> web.Response` — Partially update fields on a tab.
- `async def delete(self) -> web.Response` — Delete a tab from a dashboard.
