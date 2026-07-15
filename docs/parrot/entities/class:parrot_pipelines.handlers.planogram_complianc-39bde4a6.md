---
type: Wiki Entity
title: PlanogramComplianceHandler
id: class:parrot_pipelines.handlers.planogram_compliance.PlanogramComplianceHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST handler for planogram compliance analysis with async job support.
---

# PlanogramComplianceHandler

Defined in [`parrot_pipelines.handlers.planogram_compliance`](../summaries/mod:parrot_pipelines.handlers.planogram_compliance.md).

```python
class PlanogramComplianceHandler(BaseView)
```

REST handler for planogram compliance analysis with async job support.

Endpoints:
    POST /api/v1/planogram/compliance
        Accept multipart form-data (image + config_name), resolve planogram
        configuration from Postgres, launch async compliance pipeline job,
        and return 202 with job_id.

    GET /api/v1/planogram/compliance/<job_id>
        Poll job status. On completion returns compliance results including
        a base64-encoded rendered overlay image.

    GET /api/v1/planogram/compliance/<job_id>/sse
        Server-Sent Events stream of job status updates until terminal state.

## Methods

- `def setup(cls, app: 'WebApp', route: str='/api/v1/planogram/compliance') -> None` — Register routes and ensure JobManager is available.
- `def job_manager(self) -> JobManager` — Resolve JobManager lazily from the request's app.
- `async def post(self) -> web.Response` — Accept image + config_name, launch async compliance job, return 202.
- `async def get(self) -> web.Response` — Return job status/result or stream SSE events.
