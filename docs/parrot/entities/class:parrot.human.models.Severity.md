---
type: Wiki Entity
title: Severity
id: class:parrot.human.models.Severity
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Declared criticality of a human-interaction request.
---

# Severity

Defined in [`parrot.human.models`](../summaries/mod:parrot.human.models.md).

```python
class Severity(str, Enum)
```

Declared criticality of a human-interaction request.

Higher severity may cause the manager to skip lower-priority tiers
and start at a more appropriate level per ``EscalationPolicy.select_starting_tier``.
