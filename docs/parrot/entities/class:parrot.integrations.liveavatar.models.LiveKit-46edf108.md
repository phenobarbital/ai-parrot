---
type: Wiki Entity
title: LiveKitRoomTokens
id: class:parrot.integrations.liveavatar.models.LiveKitRoomTokens
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Viewer and agent JWT tokens for a LiveKit Cloud room.
---

# LiveKitRoomTokens

Defined in [`parrot.integrations.liveavatar.models`](../summaries/mod:parrot.integrations.liveavatar.models.md).

```python
class LiveKitRoomTokens(BaseModel)
```

Viewer and agent JWT tokens for a LiveKit Cloud room.

IMPORTANT: ``agent_token`` is server-side only. It must never be returned
in any client-facing HTTP response — the frontend receives only
``client_token``.

Attributes:
    livekit_url: LiveKit Cloud WebSocket URL (wss://<project>.livekit.cloud).
    room: Room name.
    client_token: Browser-viewer JWT (subscribe-only grants).
    agent_token: Avatar-participant JWT (publish grants, server-side only).
