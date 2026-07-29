---
type: Wiki Entity
title: DatasetManagerHandler
id: class:parrot.handlers.datasets.DatasetManagerHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP handler for managing a user's DatasetManager via REST API.
---

# DatasetManagerHandler

Defined in [`parrot.handlers.datasets`](../summaries/mod:parrot.handlers.datasets.md).

```python
class DatasetManagerHandler(BaseView)
```

HTTP handler for managing a user's DatasetManager via REST API.

Endpoints:
    GET    /api/v1/agents/datasets/{agent_id}              - List datasets
    GET    /api/v1/agents/datasets/{agent_id}/{dataset_id} - Describe a single dataset
    PATCH  /api/v1/agents/datasets/{agent_id}              - Activate/deactivate dataset
    PUT    /api/v1/agents/datasets/{agent_id}              - Upload file as dataset
    POST   /api/v1/agents/datasets/{agent_id}              - Add query as dataset
    DELETE /api/v1/agents/datasets/{agent_id}              - Delete dataset

## Methods

- `def user_objects_handler(self) -> UserObjectsHandler` — Lazy-initialized UserObjectsHandler instance.
- `async def get(self) -> web.Response` — List all datasets or describe a single dataset.
- `async def patch(self) -> web.Response` — Activate or deactivate a dataset.
- `async def put(self) -> web.Response` — Upload an Excel/CSV file as a new dataset.
- `async def post(self) -> web.Response` — Add a dataset from query/sql/datasource configuration.
- `async def delete(self) -> web.Response` — Delete a dataset from the DatasetManager.
