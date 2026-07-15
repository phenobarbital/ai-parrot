---
type: Wiki Summary
title: parrot.autonomous.orchestrator
id: mod:parrot.autonomous.orchestrator
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Autonomy Orchestrator for AI-Parrot.
relates_to:
- concept: class:parrot.autonomous.orchestrator.AutonomousOrchestrator
  rel: defines
- concept: class:parrot.autonomous.orchestrator.ExecutionRequest
  rel: defines
- concept: class:parrot.autonomous.orchestrator.ExecutionResult
  rel: defines
- concept: class:parrot.autonomous.orchestrator.ExecutionTarget
  rel: defines
- concept: mod:parrot.autonomous.admin
  rel: references
- concept: mod:parrot.autonomous.ledger
  rel: references
- concept: mod:parrot.autonomous.redis_jobs
  rel: references
- concept: mod:parrot.autonomous.webhooks
  rel: references
- concept: mod:parrot.bots
  rel: references
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.core.events
  rel: references
- concept: mod:parrot.core.exceptions
  rel: references
- concept: mod:parrot.core.hooks
  rel: references
- concept: mod:parrot.human
  rel: references
- concept: mod:parrot.integrations.telegram.combined_callback
  rel: references
- concept: mod:parrot.manager
  rel: references
- concept: mod:parrot.models.crew_definition
  rel: references
- concept: mod:parrot.observability
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.scheduler
  rel: references
---

# `parrot.autonomous.orchestrator`

Autonomy Orchestrator for AI-Parrot.

Unified orchestration layer that manages autonomous execution of:
- Individual Agents
- AgentCrews (sequential, parallel, flow, loop modes)
- AgentFlows (DAG-based workflows)

Supports multiple trigger modes:
- Scheduled (APScheduler)
- Redis Jobs (dynamic injection)
- Event Bus (pub/sub)
- Webhooks (external triggers)

## Classes

- **`ExecutionTarget(Enum)`** — Type of execution target.
- **`ExecutionRequest`** — Represents a request to execute an agent or crew.
- **`ExecutionResult`** — Result of an execution request.
- **`AutonomousOrchestrator`** — Unified orchestrator for autonomous agent and crew execution.
