---
type: Wiki Entity
title: AgentDispatcher
id: class:parrot.bots._types.AgentDispatcher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Duck-typed async callable that dispatches a named agent.
---

# AgentDispatcher

Defined in [`parrot.bots._types`](../summaries/mod:parrot.bots._types.md).

```python
class AgentDispatcher(Protocol)
```

Duck-typed async callable that dispatches a named agent.

Any object exposing a matching ``__call__`` shape satisfies this
protocol structurally — no inheritance coupling is required.
``AutonomousOrchestrator.execute_agent`` (``ai-parrot-server``) already
satisfies this shape, so it can be wired in via
``jira_specialist.set_agent_dispatcher(orchestrator.execute_agent)``
without core ever importing the server package.
