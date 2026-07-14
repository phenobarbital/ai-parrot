---
type: Wiki Entity
title: ConfirmationDecision
id: class:parrot.auth.confirmation.ConfirmationDecision
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of ConfirmationGuard.confirm().
---

# ConfirmationDecision

Defined in [`parrot.auth.confirmation`](../summaries/mod:parrot.auth.confirmation.md).

```python
class ConfirmationDecision(BaseModel)
```

Result of ConfirmationGuard.confirm().

Mirrors :class:`GuardDecision` (grants.py:320).

Attributes:
    allowed: Whether the tool call is permitted to proceed.
    status: Outcome token — one of ``confirmed``, ``cancelled``,
        ``timeout``, ``not_required``.
    reason: Human-readable explanation of the decision.
    parameters: (Possibly edited and re-validated) parameters to pass to
        ``tool.execute()``. ``None`` means use the original parameters.
