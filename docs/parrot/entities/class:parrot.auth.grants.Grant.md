---
type: Wiki Entity
title: Grant
id: class:parrot.auth.grants.Grant
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A bounded-window approval record.
---

# Grant

Defined in [`parrot.auth.grants`](../summaries/mod:parrot.auth.grants.md).

```python
class Grant(BaseModel)
```

A bounded-window approval record.

A Grant is created when a human approves a tool call via HITL. It allows
the same (owner, scope) combination to execute without re-asking until the
window expires or the grant is explicitly revoked.

Attributes:
    grant_id: Unique identifier for this grant (auto-generated UUID).
    owner_id: The actor who was granted permission (user_id or agent_id).
    scope: The permission scope, e.g. ``"tool:pulumi_apply"`` or ``"tool:*"``.
    granted_by: Identifier of the human respondent who approved.
    created_at: UTC timestamp when the grant was created.
    expires_at: UTC timestamp when the grant window closes.
    revoked: Whether the grant has been explicitly revoked before expiry.

## Methods

- `def is_active(self, now: Optional[datetime]=None) -> bool` — Return True if the grant is still within its window and not revoked.
- `def covers(self, scope: str) -> bool` — Return True if this grant covers the requested scope.
