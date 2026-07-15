---
type: Wiki Summary
title: parrot.handlers.crew.saved_execution_service
id: mod:parrot.handlers.crew.saved_execution_service
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: SavedExecutionService — orchestration layer for execution history,
relates_to:
- concept: class:parrot.handlers.crew.saved_execution_service.CrewNotFoundError
  rel: defines
- concept: class:parrot.handlers.crew.saved_execution_service.ExecutionNotFoundError
  rel: defines
- concept: class:parrot.handlers.crew.saved_execution_service.ReplayValidationError
  rel: defines
- concept: class:parrot.handlers.crew.saved_execution_service.SavedExecutionError
  rel: defines
- concept: class:parrot.handlers.crew.saved_execution_service.SavedExecutionService
  rel: defines
- concept: class:parrot.handlers.crew.saved_execution_service.SchedulerUnavailableError
  rel: defines
- concept: mod:parrot.bots.flows.core.storage.backends.base
  rel: references
- concept: mod:parrot.handlers.crew.models
  rel: references
---

# `parrot.handlers.crew.saved_execution_service`

SavedExecutionService — orchestration layer for execution history,
replay, and scheduling (FEAT-307).

Framework-agnostic: does NOT import aiohttp or any HTTP concern. The HTTP
handler (``CrewExecutionHistoryHandler``) is responsible for translating the
exceptions raised here into HTTP responses.

## Classes

- **`SavedExecutionError(ValueError)`** — Base exception for SavedExecutionService errors.
- **`ExecutionNotFoundError(SavedExecutionError)`** — The requested execution record doesn't exist (or isn't owned by the
- **`CrewNotFoundError(SavedExecutionError)`** — The crew referenced by a saved execution no longer exists (or no
- **`ReplayValidationError(SavedExecutionError)`** — The replay/schedule request fails validation for reasons other than
- **`SchedulerUnavailableError(SavedExecutionError)`** — No ``scheduler_manager`` is configured on the service.
- **`SavedExecutionService`** — Orchestration layer for execution history, replay, and scheduling.
