---
type: Wiki Summary
title: parrot.handlers.crew.models
id: mod:parrot.handlers.crew.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Data models for AgentCrew API.
relates_to:
- concept: class:parrot.handlers.crew.models.CrewJob
  rel: defines
- concept: class:parrot.handlers.crew.models.CrewJobResponse
  rel: defines
- concept: class:parrot.handlers.crew.models.CrewJobStatusResponse
  rel: defines
- concept: class:parrot.handlers.crew.models.CrewListResponse
  rel: defines
- concept: class:parrot.handlers.crew.models.CrewQueryRequest
  rel: defines
- concept: class:parrot.handlers.crew.models.ExecutionDetail
  rel: defines
- concept: class:parrot.handlers.crew.models.ExecutionFilter
  rel: defines
- concept: class:parrot.handlers.crew.models.ExecutionSummary
  rel: defines
- concept: class:parrot.handlers.crew.models.JobStatus
  rel: defines
- concept: class:parrot.handlers.crew.models.PaginatedResponse
  rel: defines
- concept: class:parrot.handlers.crew.models.ReplayRequest
  rel: defines
- concept: class:parrot.handlers.crew.models.ScheduleRequest
  rel: defines
- concept: mod:parrot.models.crew_definition
  rel: references
---

# `parrot.handlers.crew.models`

Data models for AgentCrew API.

Defines structures for crew definitions, job management, and execution tracking.

The core definition models (ExecutionMode, AgentDefinition, FlowRelation,
CrewDefinition) now live in ``parrot.models.crew_definition`` and are
re-exported here for backward compatibility.

## Classes

- **`JobStatus(str, Enum)`** — Status of async job execution.
- **`CrewQueryRequest(BaseModel)`** — Request to query a crew.
- **`CrewJob`** — Represents an asynchronous crew execution job.
- **`CrewListResponse(BaseModel)`** — Response for listing crews.
- **`CrewJobResponse(BaseModel)`** — Response when creating a new job.
- **`CrewJobStatusResponse(BaseModel)`** — Response for job status check.
- **`ExecutionFilter(BaseModel)`** — Filters for listing saved executions.
- **`ExecutionSummary(BaseModel)`** — Summary of a saved execution for list responses.
- **`ExecutionDetail(ExecutionSummary)`** — Full execution record with payload, extending :class:`ExecutionSummary`.
- **`ReplayRequest(BaseModel)`** — Request body for replaying a saved execution.
- **`ScheduleRequest(BaseModel)`** — Request body for scheduling a saved execution.
- **`PaginatedResponse(BaseModel)`** — Paginated list response.
