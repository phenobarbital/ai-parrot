---
type: Wiki Entity
title: ConnectInitRequest
id: class:parrot.auth.oauth2.models.ConnectInitRequest
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Request body for ``POST .../integrations/{agent_id}/{provider}/connect``.
---

# ConnectInitRequest

Defined in [`parrot.auth.oauth2.models`](../summaries/mod:parrot.auth.oauth2.models.md).

```python
class ConnectInitRequest(BaseModel)
```

Request body for ``POST .../integrations/{agent_id}/{provider}/connect``.

Attributes:
    return_origin: The caller's ``window.location.origin`` used as the
        ``postMessage`` target in the popup callback page.  When absent,
        the server reads ``request.headers["Origin"]``.
