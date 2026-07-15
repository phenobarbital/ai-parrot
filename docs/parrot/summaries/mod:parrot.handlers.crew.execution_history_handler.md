---
type: Wiki Summary
title: parrot.handlers.crew.execution_history_handler
id: mod:parrot.handlers.crew.execution_history_handler
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST API Handler for AgentCrew Saved Execution History (FEAT-307).
relates_to:
- concept: class:parrot.handlers.crew.execution_history_handler.CrewExecutionHistoryHandler
  rel: defines
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: references
- concept: mod:parrot.handlers.crew.models
  rel: references
- concept: mod:parrot.handlers.crew.saved_execution_service
  rel: references
---

# `parrot.handlers.crew.execution_history_handler`

REST API Handler for AgentCrew Saved Execution History (FEAT-307).

Exposes list/detail/replay/schedule/delete operations over saved crew
executions, backed by ``SavedExecutionService``.

Endpoints:
    GET    /api/v1/crew/executions                       - list executions
    GET    /api/v1/crew/executions/{execution_id}         - execution detail
    POST   /api/v1/crew/executions/{execution_id}/replay   - replay execution
    POST   /api/v1/crew/executions/{execution_id}/schedule - schedule execution
    DELETE /api/v1/crew/executions/{execution_id}         - delete execution

## Classes

- **`CrewExecutionHistoryHandler(BaseView)`** — REST API Handler for saved crew execution history, replay, and scheduling.
