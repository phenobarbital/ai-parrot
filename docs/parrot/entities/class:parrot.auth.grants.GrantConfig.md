---
type: Wiki Entity
title: GrantConfig
id: class:parrot.auth.grants.GrantConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configurable defaults for the grant subsystem.
---

# GrantConfig

Defined in [`parrot.auth.grants`](../summaries/mod:parrot.auth.grants.md).

```python
class GrantConfig(BaseModel)
```

Configurable defaults for the grant subsystem.

Attributes:
    window_seconds: Default approval window in seconds (default 15 min).
    approval_timeout: Seconds to wait for a human response before
        timing out and failing closed (default 120 s).
    default_channel: HITL channel to use for approval requests
        (default ``"telegram"``).
