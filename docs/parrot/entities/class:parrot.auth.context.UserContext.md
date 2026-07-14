---
type: Wiki Entity
title: UserContext
id: class:parrot.auth.context.UserContext
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Channel-agnostic identity snapshot for a single end user.
---

# UserContext

Defined in [`parrot.auth.context`](../summaries/mod:parrot.auth.context.md).

```python
class UserContext
```

Channel-agnostic identity snapshot for a single end user.

Built by the integration wrapper at authentication time (or lazily on
first authenticated message) and passed to the agent so per-user
initialization (credentials, tool bindings, caches) can happen without
leaking integration types into bot code.

Attributes:
    channel: Short identifier of the source channel (``"telegram"``,
        ``"msteams"``, ``"slack"``, ``"http"``).
    user_id: Stable per-channel user identifier used to look up
        credentials (e.g. ``"tg:123456"`` or a Navigator user id).
    display_name: Human-readable name. Optional.
    email: Primary email address. Optional.
    session_id: Stable session id for conversation memory keying.
        Optional — the bot falls back to its own conventions when
        absent.
    metadata: Free-form extras an integration wants to pass through
        (e.g. ``{"jira_account_id": ..., "telegram_username": ...}``).
        Frozen-dataclass mutability is intentionally restricted; pass
        a fresh ``UserContext`` when the state changes.
