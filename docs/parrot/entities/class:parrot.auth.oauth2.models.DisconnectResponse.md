---
type: Wiki Entity
title: DisconnectResponse
id: class:parrot.auth.oauth2.models.DisconnectResponse
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Response for the disconnect endpoint.
---

# DisconnectResponse

Defined in [`parrot.auth.oauth2.models`](../summaries/mod:parrot.auth.oauth2.models.md).

```python
class DisconnectResponse(BaseModel)
```

Response for the disconnect endpoint.

Attributes:
    provider: Provider that was disconnected.
    disconnected: Always ``True`` on success.
