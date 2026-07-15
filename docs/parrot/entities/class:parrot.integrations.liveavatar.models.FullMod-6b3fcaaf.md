---
type: Wiki Entity
title: FullModeSessionHandle
id: class:parrot.integrations.liveavatar.models.FullModeSessionHandle
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Runtime handle for a LiveAvatar FULL mode session.
relates_to:
- concept: class:parrot.integrations.liveavatar.models.AvatarSessionHandle
  rel: extends
---

# FullModeSessionHandle

Defined in [`parrot.integrations.liveavatar.models`](../summaries/mod:parrot.integrations.liveavatar.models.md).

```python
class FullModeSessionHandle(AvatarSessionHandle)
```

Runtime handle for a LiveAvatar FULL mode session.

Extends :class:`AvatarSessionHandle` with the LiveKit room credentials
returned by the FULL mode ``/start`` response.

NOTE: ``ws_url`` is inherited from :class:`AvatarSessionHandle` but is
unused in FULL mode (LITE-only).  It is always empty in FULL mode sessions —
this is harmless but callers should not rely on it.

Attributes:
    livekit_url: LiveKit WebSocket URL for the browser to connect to the
        avatar-managed room.  Safe to return to the client.
    livekit_client_token: Subscribe-only browser JWT for the LiveKit room.
        Safe to return to the client.
