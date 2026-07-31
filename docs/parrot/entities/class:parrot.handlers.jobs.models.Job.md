---
type: Wiki Entity
title: Job
id: class:parrot.handlers.jobs.models.Job
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Represents an asynchronous execution job.
---

# Job

Defined in [`parrot.handlers.jobs.models`](../summaries/mod:parrot.handlers.jobs.models.md).

```python
class Job
```

Represents an asynchronous execution job.

## Methods

- `def id(self) -> str` — Job ID (RQ uses 'id', yours uses 'job_id').
- `def get_status(self) -> str` — Get job status as string.
- `def elapsed_time(self) -> Optional[float]` — Calculate elapsed time in seconds.
- `def to_dict(self) -> Dict[str, Any]` — Convert to dictionary.
- `def is_finished(self) -> bool` — Check if job completed successfully.
- `def is_failed(self) -> bool` — Check if job failed.
- `def is_started(self) -> bool` — Check if job has started.
- `def is_queued(self) -> bool` — Check if job is queued.
- `def exc_info(self) -> Optional[str]` — Exception info (RQ uses 'exc_info', yours uses 'error').
- `def ended_at(self) -> Optional[datetime]` — When job ended (RQ uses 'ended_at', yours uses 'completed_at').
- `def meta(self) -> Dict[str, Any]` — Job metadata (for progress tracking, etc.).
- `def refresh(self)` — Refresh job data (RQ jobs have this method).
