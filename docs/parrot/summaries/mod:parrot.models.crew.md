---
type: Wiki Summary
title: parrot.models.crew
id: mod:parrot.models.crew
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Data models for Agent Crew execution results.
relates_to:
- concept: class:parrot.models.crew.AgentExecutionInfo
  rel: defines
- concept: class:parrot.models.crew.AgentResult
  rel: defines
- concept: class:parrot.models.crew.CrewResult
  rel: defines
- concept: class:parrot.models.crew.VectorStoreProtocol
  rel: defines
- concept: func:parrot.models.crew.build_agent_metadata
  rel: defines
- concept: func:parrot.models.crew.determine_run_status
  rel: defines
- concept: mod:parrot.models.responses
  rel: references
---

# `parrot.models.crew`

Data models for Agent Crew execution results.

Provides standardized output format for all crew execution modes.

## Classes

- **`AgentExecutionInfo`** — Information about an agent's execution in a crew workflow.
- **`CrewResult`** — Standardized result from crew execution.
- **`AgentResult`** — Captures a single agent execution with full context
- **`VectorStoreProtocol(Protocol)`** — Protocol for vector store implementations

## Functions

- `def determine_run_status(success_count: int, failure_count: int) -> Literal['completed', 'partial', 'failed']` — Compute the overall status for a crew execution.
- `def build_agent_metadata(agent_id: str, agent: Optional[Any], response: Optional[ResponseType], output: Optional[Any], execution_time: float, status: str, error: Optional[str]=None) -> AgentExecutionInfo` — Create execution metadata for an agent run.
