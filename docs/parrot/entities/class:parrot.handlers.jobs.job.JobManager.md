---
type: Wiki Entity
title: JobManager
id: class:parrot.handlers.jobs.job.JobManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages asynchronous job execution for crew operations.
---

# JobManager

Defined in [`parrot.handlers.jobs.job`](../summaries/mod:parrot.handlers.jobs.job.md).

```python
class JobManager
```

Manages asynchronous job execution for crew operations.

Provides:
- Job creation and tracking
- Async execution with asyncio.create_task
- Status monitoring
- Result retrieval
- Automatic cleanup of old jobs
- Optional Redis-backed persistence via RedisJobStore

Args:
    id: Logical identifier for this manager instance.
    cleanup_interval: Seconds between automatic cleanup sweeps.
    job_ttl: Seconds to keep completed/failed jobs in memory (and Redis).
    store: Optional ``RedisJobStore`` instance.  When supplied every
        job create/update/delete is also mirrored to Redis so that
        job state survives server restarts.

## Methods

- `async def start(self) -> None` — Start the job manager and periodic cleanup task.
- `async def stop(self) -> None` — Stop the job manager and cancel all running tasks.
- `def create_job(self, job_id: str, obj_id: str, query: Any, user_id: Optional[str]=None, session_id: Optional[str]=None, execution_mode: Optional[str]=None) -> Job` — Create a new job and register it in memory (and Redis if configured).
- `async def execute_job(self, job_id: str, execution_func: Callable[[], Awaitable[Any]]) -> None` — Schedule a job for async execution.
- `def get_job(self, job_id: str) -> Optional[Job]` — Return a job from the in-memory store.
- `async def get_job_async(self, job_id: str) -> Optional[Job]` — Return a job from memory or Redis.
- `def list_jobs(self, obj_id: Optional[str]=None, status: Optional[JobStatus]=None, limit: int=100) -> list` — List in-memory jobs with optional filtering (newest first).
- `async def list_jobs_async(self, obj_id: Optional[str]=None, status: Optional[JobStatus]=None, limit: int=100) -> list` — List jobs from Redis (if store configured) or memory.
- `def delete_job(self, job_id: str) -> bool` — Delete a job from memory (and Redis if configured).
- `def get_stats(self) -> Dict[str, Any]` — Return statistics about the in-memory job queue.
- `def enqueue(self, func: Callable, args: tuple=None, kwargs: dict=None, queue: str='default', timeout: Optional[int]=None, result_ttl: Optional[int]=None, job_id: Optional[str]=None, **extra_kwargs) -> Job` — Enqueue a function for async execution (RQ-compatible API).
- `def fetch_job(self, job_id: str) -> Optional[Job]` — Fetch a job by ID (RQ-compatible API).
