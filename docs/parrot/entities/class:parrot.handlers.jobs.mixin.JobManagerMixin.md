---
type: Wiki Entity
title: JobManagerMixin
id: class:parrot.handlers.jobs.mixin.JobManagerMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin class to add job manager functionality to any BaseView.
---

# JobManagerMixin

Defined in [`parrot.handlers.jobs.mixin`](../summaries/mod:parrot.handlers.jobs.mixin.md).

```python
class JobManagerMixin
```

Mixin class to add job manager functionality to any BaseView.

This mixin allows view methods to be executed asynchronously via a job manager,
and provides automatic handling of job status/result retrieval via GET requests.

Attributes:
    job_manager: An instance of JobManager that handles async job execution
    job_id_param: The query parameter name for job IDs (default: 'job_id')

## Methods

- `def as_job(queue: str='default', timeout: Optional[int]=None, result_ttl: Optional[int]=500, return_job_id: bool=True) -> Callable` — Decorator to enqueue a method to be executed by the job manager.
- `def get(self, request, *args, **kwargs)` — Override GET method to handle job_id parameter.
- `def get_async_methods(cls) -> Dict[str, Dict[str, Any]]` — Get all methods decorated with @as_job in the class.
