---
type: Wiki Entity
title: AgentFactoryOrchestrator
id: class:parrot.bots.factory.orchestrator.AgentFactoryOrchestrator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestrate router → specialist → finalize with HITL gates.
---

# AgentFactoryOrchestrator

Defined in [`parrot.bots.factory.orchestrator`](../summaries/mod:parrot.bots.factory.orchestrator.md).

```python
class AgentFactoryOrchestrator
```

Orchestrate router → specialist → finalize with HITL gates.

## Methods

- `async def run(self, request: FactoryRequest) -> FactoryResult` — Drive the full factory flow for a single user request.
