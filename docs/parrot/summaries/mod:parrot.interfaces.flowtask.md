---
type: Wiki Summary
title: parrot.interfaces.flowtask
id: mod:parrot.interfaces.flowtask
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Flowtask Interface - Mixin for managing Flowtask DAG tasks.
relates_to:
- concept: class:parrot.interfaces.flowtask.FlowtaskInterface
  rel: defines
- concept: class:parrot.interfaces.flowtask.JobInfo
  rel: defines
- concept: class:parrot.interfaces.flowtask.TaskCodeFormat
  rel: defines
- concept: class:parrot.interfaces.flowtask.TaskCodeRequest
  rel: defines
- concept: class:parrot.interfaces.flowtask.TaskExecutionRequest
  rel: defines
- concept: class:parrot.interfaces.flowtask.TaskResult
  rel: defines
- concept: class:parrot.interfaces.flowtask.TaskStatus
  rel: defines
- concept: class:parrot.interfaces.flowtask.WorkerTaskRequest
  rel: defines
---

# `parrot.interfaces.flowtask`

Flowtask Interface - Mixin for managing Flowtask DAG tasks.

Provides async methods for interacting with the Flowtask API:
- Execute tasks locally or remotely via REST API
- Launch long-running tasks on workers
- Submit ad-hoc tasks from JSON/YAML definitions
- Query task and job status
- List available programs and tasks

Flowtask (github.com/phenobarbital/flowtask) is a plugin-based,
component-driven task execution framework that runs DAG-based workflows
defined in JSON, YAML, or TOML files.

Environment Variables:
    TASK_DOMAIN: Base URL of the Flowtask API server (required for remote ops).
    TASK_API_TOKEN: Optional Bearer token for authenticated endpoints.

## Classes

- **`TaskStatus(str, Enum)`** — Possible statuses of a Flowtask task/job.
- **`TaskCodeFormat(str, Enum)`** — Supported formats for ad-hoc task definitions.
- **`TaskExecutionRequest(BaseModel)`** — Request model for executing a Flowtask task.
- **`TaskCodeRequest(BaseModel)`** — Request model for submitting an ad-hoc task from a JSON/YAML string.
- **`WorkerTaskRequest(BaseModel)`** — Request model for dispatching a task to a Flowtask worker.
- **`TaskResult(BaseModel)`** — Response model for a completed task execution.
- **`JobInfo(BaseModel)`** — Lightweight info about a queued/running job.
- **`FlowtaskInterface`** — Interface for managing Flowtask DAG tasks.
