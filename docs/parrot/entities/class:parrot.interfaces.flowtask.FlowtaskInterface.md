---
type: Wiki Entity
title: FlowtaskInterface
id: class:parrot.interfaces.flowtask.FlowtaskInterface
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Interface for managing Flowtask DAG tasks.
---

# FlowtaskInterface

Defined in [`parrot.interfaces.flowtask`](../summaries/mod:parrot.interfaces.flowtask.md).

```python
class FlowtaskInterface
```

Interface for managing Flowtask DAG tasks.

Mix this into a bot or service class to gain async helpers for:

- **run_task** / **run_task_remote** — execute a task locally or via API.
- **dispatch_task** — enqueue a task on a Flowtask worker.
- **submit_task_code** — send an ad-hoc JSON/YAML task definition.
- **get_job_status** — poll a running/queued job.
- **list_programs** / **list_tasks** — discover available programs & tasks.
- **cancel_job** — cancel a queued or running job.

All remote methods require the ``TASK_DOMAIN`` environment variable.

## Methods

- `async def run_task_remote(self, request: Union[TaskExecutionRequest, Dict[str, Any]]) -> TaskResult` — Execute a Flowtask task via the remote API.
- `async def run_task_local(self, request: Union[TaskExecutionRequest, Dict[str, Any]]) -> TaskResult` — Execute a Flowtask task locally using the flowtask library.
- `async def dispatch_task(self, request: Union[WorkerTaskRequest, Dict[str, Any]]) -> TaskResult` — Dispatch a task to a Flowtask worker for background execution.
- `async def submit_task_code(self, request: Union[TaskCodeRequest, Dict[str, Any]]) -> TaskResult` — Submit an ad-hoc task definition as a JSON or YAML string.
- `async def submit_task_code_local(self, request: Union[TaskCodeRequest, Dict[str, Any]]) -> TaskResult` — Execute an ad-hoc task definition locally via the flowtask library.
- `async def get_job_status(self, job_id: str) -> JobInfo` — Query the status of a queued/running Flowtask job.
- `async def cancel_job(self, job_id: str) -> TaskResult` — Cancel a queued or running Flowtask job.
- `async def list_programs(self) -> List[str]` — List available Flowtask programs.
- `async def list_tasks(self, program: str) -> List[Dict[str, Any]]` — List tasks available under a given program.
- `async def get_task_info(self, program: str, task_name: str) -> Dict[str, Any]` — Get detailed information about a specific task definition.
