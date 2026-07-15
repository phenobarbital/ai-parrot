---
type: Wiki Summary
title: parrot.bots.factory.orchestrator
id: mod:parrot.bots.factory.orchestrator
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AgentFactoryOrchestrator — the user-facing entry point of the factory.
relates_to:
- concept: class:parrot.bots.factory.orchestrator.AgentFactoryOrchestrator
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.bots.factory
  rel: references
- concept: mod:parrot.bots.factory.contracts
  rel: references
- concept: mod:parrot.bots.factory.tools.finalize
  rel: references
- concept: mod:parrot.bots.factory.tools.introspection
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.human.manager
  rel: references
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.bots.factory.orchestrator`

AgentFactoryOrchestrator — the user-facing entry point of the factory.

The orchestrator runs a small LLM router to pick a specialist, gates that
choice through a pre-delegation HITL checkpoint, delegates the actual
drafting to the specialist, gates the resulting ``AgentDefinition`` through a
pre-finalize HITL checkpoint, and finally writes + registers the YAML.

The two HITL checkpoints are the cost-protection mechanism: if the user
times out or cancels at either gate, the orchestrator returns immediately
without invoking the next LLM stage.

## Classes

- **`AgentFactoryOrchestrator`** — Orchestrate router → specialist → finalize with HITL gates.
