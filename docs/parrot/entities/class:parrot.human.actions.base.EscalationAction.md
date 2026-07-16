---
type: Wiki Entity
title: EscalationAction
id: class:parrot.human.actions.base.EscalationAction
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base for escalation logic that triggers external systems.
---

# EscalationAction

Defined in [`parrot.human.actions.base`](../summaries/mod:parrot.human.actions.base.md).

```python
class EscalationAction(ABC)
```

Abstract base for escalation logic that triggers external systems.

## Methods

- `async def execute(self, interaction: 'HumanInteraction', tier: 'EscalationTier') -> Dict[str, Any]` — Execute the escalation action.
