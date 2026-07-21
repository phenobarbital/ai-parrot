---
type: Wiki Entity
title: DeepLink
id: class:parrot.outputs.a2ui.artifacts.DeepLink
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single-use, TTL-bound deep link that resumes the originating channel.
---

# DeepLink

Defined in [`parrot.outputs.a2ui.artifacts`](../summaries/mod:parrot.outputs.a2ui.artifacts.md).

```python
class DeepLink(BaseModel)
```

A single-use, TTL-bound deep link that resumes the originating channel.

Minted by the Module 8 :class:`DeepLinkService`; the model itself ships here.

Attributes:
    action_label: Human-readable label for the action the link resumes.
    url: Channel resume URL embedding the opaque token.
    token_id: Token identifier for audit / consume tracking.
    expires_at: Expiry timestamp (UTC).
