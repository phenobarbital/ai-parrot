---
type: Wiki Entity
title: CredentialRequired
id: class:parrot.auth.credentials.CredentialRequired
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised by the tool-loop seam when the broker returns :class:`NeedsAuth`.
---

# CredentialRequired

Defined in [`parrot.auth.credentials`](../summaries/mod:parrot.auth.credentials.md).

```python
class CredentialRequired(Exception)
```

Raised by the tool-loop seam when the broker returns :class:`NeedsAuth`.

This is the canonical, surface-neutral exception.  Each surface catches it
and renders the appropriate UX:

* A2A: suspend + TEXT consent link.
* MSAgentSDK: Adaptive Card (static key) or OAuthCard (OAuth/OBO).
* CLI: plain URL printed to stdout.

Args:
    provider: Provider identifier.
    auth_url: Consent / OOB capture URL (NEVER a secret).
    auth_kind: Auth kind for surface rendering.
    user_code: Device-code flow only (FEAT-266, keyword-only) — the short
        code the user enters at ``verification_uri``.
    verification_uri: Device-code flow only (FEAT-266, keyword-only) —
        the Microsoft device-login URL.
    expires_in: Device-code flow only (FEAT-266, keyword-only) — seconds
        until the device code expires.
