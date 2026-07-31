---
type: Wiki Entity
title: ScrapingHandler
id: class:parrot.handlers.scraping.handler.ScrapingHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Class-based HTTP view for /api/v1/scraping/.
---

# ScrapingHandler

Defined in [`parrot.handlers.scraping.handler`](../summaries/mod:parrot.handlers.scraping.handler.md).

```python
class ScrapingHandler(BaseView)
```

Class-based HTTP view for /api/v1/scraping/.

Handles plan CRUD (create via LLM, list, load, save, delete) and
scrape/crawl execution via JobManager for async processing.

Routes:
    GET    /plans           — list saved plans
    GET    /plans/{name}    — load a specific plan
    POST   /plans           — create a plan via LLM
    PUT    /plans/{name}    — save/update a plan
    PATCH  /plans/{name}    — partial update (reserved)
    PATCH  /jobs/{job_id}   — check job status
    DELETE /plans/{name}    — delete a plan
    POST   /scrape          — submit a scraping job
    POST   /crawl           — submit a crawl job

## Methods

- `def post_init(self, *args, **kwargs)` — Post-initialization hook called by BaseView.
- `async def get(self) -> web.Response` — Handle GET requests.
- `async def post(self) -> web.Response` — Handle POST requests.
- `async def put(self) -> web.Response` — PUT /plans/{name} — save or update a plan.
- `async def patch(self) -> web.Response` — PATCH /{job_id} — check job status and retrieve results.
- `async def delete(self) -> web.Response` — DELETE /plans/{name} — delete a plan by name.
- `def setup(cls, app: web.Application) -> None` — Register routes and lifecycle signals on the aiohttp application.
