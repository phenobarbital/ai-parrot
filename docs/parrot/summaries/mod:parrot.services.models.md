---
type: Wiki Summary
title: parrot.services.models
id: mod:parrot.services.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic models and configuration for AgentService.
relates_to:
- concept: class:parrot.services.models.AgentServiceConfig
  rel: defines
- concept: class:parrot.services.models.AgentTask
  rel: defines
- concept: class:parrot.services.models.DeliveryChannel
  rel: defines
- concept: class:parrot.services.models.DeliveryConfig
  rel: defines
- concept: class:parrot.services.models.HeartbeatConfig
  rel: defines
- concept: class:parrot.services.models.TaskPriority
  rel: defines
- concept: class:parrot.services.models.TaskResult
  rel: defines
- concept: class:parrot.services.models.TaskStatus
  rel: defines
---

# `parrot.services.models`

Pydantic models and configuration for AgentService.

## Classes

- **`DeliveryChannel(str, Enum)`** — Supported delivery channels for task results.
- **`TaskPriority(int, Enum)`** — Task priority levels (lower = higher priority).
- **`TaskStatus(str, Enum)`** — Task lifecycle states.
- **`DeliveryConfig(BaseModel)`** — Channel-specific delivery parameters.
- **`AgentTask(BaseModel)`** — A task to be executed by an agent.
- **`TaskResult(BaseModel)`** — Result of an agent task execution.
- **`HeartbeatConfig(BaseModel)`** — Configuration for periodic agent heartbeats.
- **`AgentServiceConfig(BaseModel)`** — Top-level configuration for AgentService.
