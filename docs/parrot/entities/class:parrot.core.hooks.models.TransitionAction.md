---
type: Wiki Entity
title: TransitionAction
id: class:parrot.core.hooks.models.TransitionAction
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single transition-to-action mapping.
---

# TransitionAction

Defined in [`parrot.core.hooks.models`](../summaries/mod:parrot.core.hooks.models.md).

```python
class TransitionAction(BaseModel)
```

A single transition-to-action mapping.

Matches when the ticket's from_status and to_status match the
configured patterns. Use ``"*"`` as a wildcard for either field.

## Methods

- `def validate_not_both_wildcards(self) -> 'TransitionAction'` — Reject configurations where both statuses are wildcards.
