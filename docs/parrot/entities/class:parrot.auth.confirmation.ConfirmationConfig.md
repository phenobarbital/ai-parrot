---
type: Wiki Entity
title: ConfirmationConfig
id: class:parrot.auth.confirmation.ConfirmationConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configurable defaults for the confirmation subsystem.
---

# ConfirmationConfig

Defined in [`parrot.auth.confirmation`](../summaries/mod:parrot.auth.confirmation.md).

```python
class ConfirmationConfig(BaseModel)
```

Configurable defaults for the confirmation subsystem.

Mirrors :class:`GrantConfig` (grants.py:95).

Attributes:
    window_seconds: Default approval window in seconds.
        ``0`` (default) means "always re-ask" — the safe, per-call default.
    approval_timeout: Seconds to wait for a human response before
        timing out and failing closed (default 120 s).
    default_channel: HITL channel to use when the permission context
        does not specify one (default ``"telegram"``).
    max_edit_retries: Maximum number of times the guard re-asks after
        invalid edited values before auto-cancelling (default 1).
