---
type: Wiki Entity
title: AsyncJobManagerMixin
id: class:parrot.handlers.jobs.mixin.AsyncJobManagerMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async-native mixin for aiohttp views with job manager functionality.
---

# AsyncJobManagerMixin

Defined in [`parrot.handlers.jobs.mixin`](../summaries/mod:parrot.handlers.jobs.mixin.md).

```python
class AsyncJobManagerMixin
```

Async-native mixin for aiohttp views with job manager functionality.

Unlike the sync JobManagerMixin (designed for RQ), this version:
- Works natively with aiohttp's async request handlers
- Supports both your asyncio JobManager and RQ Queue
- Provides async get() method
- Handles aiohttp request objects

Usage with aiohttp:
    class MyView(AsyncJobManagerMixin, web.View):
        def __init__(self, request):
            super().__init__(request)
            # Use either RQ Queue or adapted JobManager
            self.job_manager = request.app['job_queue']

        @AsyncJobManagerMixin.as_job(queue="tasks", timeout=3600)
        async def post(self):
            # Your async handler
            return {"result": "success"}

        async def get(self):
            # Automatically handles job_id parameter
            return await super().get()

## Methods

- `def as_job(queue: str='default', timeout: Optional[int]=None, result_ttl: Optional[int]=500, return_job_id: bool=True, async_execution: bool=True) -> Callable` — Decorator to enqueue an async method for job execution.
- `async def get(self) -> web.Response` — Async GET method to handle job status requests.
- `def get_async_methods(cls) -> Dict[str, Dict[str, Any]]` — Get all methods decorated with @as_job.
