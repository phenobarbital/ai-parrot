---
type: Wiki Entity
title: GuardDecision
id: class:parrot.auth.grants.GuardDecision
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of GrantGuard.authorize().
---

# GuardDecision

Defined in [`parrot.auth.grants`](../summaries/mod:parrot.auth.grants.md).

```python
class GuardDecision(BaseModel)
```

Result of GrantGuard.authorize().

Attributes:
    allowed: Whether the tool call is permitted.
    reason: Human-readable explanation of the decision.
    grant: The Grant that authorized this call (None if not allowed or
        if the tool did not require a grant).
