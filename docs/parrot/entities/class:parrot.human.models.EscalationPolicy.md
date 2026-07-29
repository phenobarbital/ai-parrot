---
type: Wiki Entity
title: EscalationPolicy
id: class:parrot.human.models.EscalationPolicy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A series of tiered levels for escalating human-in-the-loop requests.
---

# EscalationPolicy

Defined in [`parrot.human.models`](../summaries/mod:parrot.human.models.md).

```python
class EscalationPolicy(BaseModel)
```

A series of tiered levels for escalating human-in-the-loop requests.

## Methods

- `def select_starting_tier(self, severity: 'Severity', now: datetime) -> Optional['EscalationTier']` — Return the first applicable tier for the given severity and time.
