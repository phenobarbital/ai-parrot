---
type: Wiki Entity
title: RouterDecision
id: class:parrot.bots.factory.contracts.RouterDecision
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'First-stage output: which specialist the orchestrator wants to invoke.'
---

# RouterDecision

Defined in [`parrot.bots.factory.contracts`](../summaries/mod:parrot.bots.factory.contracts.md).

```python
class RouterDecision(BaseModel)
```

First-stage output: which specialist the orchestrator wants to invoke.

The LLM emits this via structured output. The orchestrator then surfaces
it through ``HITLCheckpoint.PRE_DELEGATION`` for user confirmation before
paying for the specialist's tokens.
