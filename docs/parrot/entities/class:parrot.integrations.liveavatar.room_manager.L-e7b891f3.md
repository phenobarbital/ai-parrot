---
type: Wiki Entity
title: LiveKitRoomManager
id: class:parrot.integrations.liveavatar.room_manager.LiveKitRoomManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mint LiveKit Cloud room tokens for the BYO transport.
---

# LiveKitRoomManager

Defined in [`parrot.integrations.liveavatar.room_manager`](../summaries/mod:parrot.integrations.liveavatar.room_manager.md).

```python
class LiveKitRoomManager
```

Mint LiveKit Cloud room tokens for the BYO transport.

Creates two JWTs per room:
- ``client_token``: subscribe-only, safe to send to the browser viewer.
- ``agent_token``: publish + subscribe, kept server-side only (never
  serialised into client responses).

Args:
    url: LiveKit WebSocket URL (defaults to ``LIVEKIT_URL`` env).
    api_key: LiveKit API key (defaults to ``LIVEKIT_API_KEY`` env).
    api_secret: LiveKit API secret (defaults to ``LIVEKIT_API_SECRET`` env).

Raises:
    KeyError: If a required env var is missing and no value is supplied.

## Methods

- `def mint_room_tokens(self, room: str, identity: str) -> LiveKitRoomTokens` — Mint viewer and agent JWT tokens for a LiveKit room.
