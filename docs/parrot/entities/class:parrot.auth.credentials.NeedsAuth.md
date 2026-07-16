---
type: Wiki Entity
title: NeedsAuth
id: class:parrot.auth.credentials.NeedsAuth
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Surface-neutral miss signal from the broker.
---

# NeedsAuth

Defined in [`parrot.auth.credentials`](../summaries/mod:parrot.auth.credentials.md).

```python
class NeedsAuth(BaseModel)
```

Surface-neutral miss signal from the broker.

Attributes:
    provider: Provider identifier.
    auth_url: Consent / OOB capture URL the user must visit.
        **NEVER** a secret.
    auth_kind: Drives surface rendering (card type).
    user_code: Device-code flow only (FEAT-266) — the short code the
        user enters at ``verification_uri``. ``None`` for non-device-code
        auth kinds.
    verification_uri: Device-code flow only (FEAT-266) — the Microsoft
        device-login URL. ``None`` for non-device-code auth kinds.
    expires_in: Device-code flow only (FEAT-266) — seconds until the
        device code expires. ``None`` for non-device-code auth kinds.
