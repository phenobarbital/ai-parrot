---
type: Wiki Entity
title: ActionBackend
id: class:parrot.human.actions.backends.base.ActionBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for concrete escalation action backends.
---

# ActionBackend

Defined in [`parrot.human.actions.backends.base`](../summaries/mod:parrot.human.actions.backends.base.md).

```python
class ActionBackend(ABC)
```

Abstract base class for concrete escalation action backends.

Each backend receives a :class:`~parrot.human.models.HumanInteraction` and
the :class:`~parrot.human.models.EscalationTier` whose
``action_metadata`` configures the specific backend parameters.

Backends MUST:
- Be fully async.
- Return a dict containing at minimum ``{"message": "<string for LLM>"}``.
- Raise a typed subclass of :class:`ActionBackendError` on failure (never
  swallow exceptions silently).
- NOT log credentials or tokens.

## Methods

- `async def execute(self, interaction: 'HumanInteraction', tier: 'EscalationTier') -> Dict[str, Any]` — Execute the action for the given interaction and tier.
