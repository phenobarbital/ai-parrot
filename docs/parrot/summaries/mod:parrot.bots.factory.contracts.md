---
type: Wiki Summary
title: parrot.bots.factory.contracts
id: mod:parrot.bots.factory.contracts
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic contracts for the Agent Factory subsystem.
relates_to:
- concept: class:parrot.bots.factory.contracts.BuilderOutput
  rel: defines
- concept: class:parrot.bots.factory.contracts.BuilderType
  rel: defines
- concept: class:parrot.bots.factory.contracts.FactoryRequest
  rel: defines
- concept: class:parrot.bots.factory.contracts.FactoryResult
  rel: defines
- concept: class:parrot.bots.factory.contracts.FactoryStatus
  rel: defines
- concept: class:parrot.bots.factory.contracts.HITLCheckpoint
  rel: defines
- concept: class:parrot.bots.factory.contracts.ProvisioningRecord
  rel: defines
- concept: class:parrot.bots.factory.contracts.RouterDecision
  rel: defines
- concept: mod:parrot.registry.registry
  rel: references
---

# `parrot.bots.factory.contracts`

Pydantic contracts for the Agent Factory subsystem.

The factory orchestrates several specialist builder agents (RAG, tool-agent,
clone). Every specialist produces the same end-shape: a ``BotConfig`` ready to
be persisted as YAML and registered with the ``AgentRegistry``. The wrapper
types below carry orchestrator-level state (routing decisions, provisioning
side-effects, HITL outcomes) around that shared payload.

The ``AgentDefinition`` alias points at ``BotConfig`` deliberately — there is
exactly one source of truth for the registry schema and the factory consumes
it directly to avoid drift.

## Classes

- **`BuilderType(str, Enum)`** — Specialist builders the orchestrator can delegate to.
- **`HITLCheckpoint(str, Enum)`** — Named human-in-the-loop checkpoints in the factory flow.
- **`FactoryStatus(str, Enum)`** — Terminal states for a factory run.
- **`FactoryRequest(BaseModel)`** — User-facing input to the orchestrator.
- **`RouterDecision(BaseModel)`** — First-stage output: which specialist the orchestrator wants to invoke.
- **`ProvisioningRecord(BaseModel)`** — Side-effect produced by a builder while drafting the definition.
- **`BuilderOutput(BaseModel)`** — Specialist-to-orchestrator handoff payload.
- **`FactoryResult(BaseModel)`** — Terminal output of an orchestrator run.
