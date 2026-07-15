---
type: Wiki Entity
title: SetContextAction
id: class:parrot.bots.flows.flow.actions.SetContextAction
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract a value from the result and set it in the shared context.
---

# SetContextAction

Defined in [`parrot.bots.flows.flow.actions`](../summaries/mod:parrot.bots.flows.flow.actions.md).

```python
class SetContextAction(BaseAction)
```

Extract a value from the result and set it in the shared context.

Uses dot-notation to navigate nested structures (e.g., "result.decision.value").
