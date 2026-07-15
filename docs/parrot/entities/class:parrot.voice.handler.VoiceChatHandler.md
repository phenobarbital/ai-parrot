---
type: Wiki Entity
title: VoiceChatHandler
id: class:parrot.voice.handler.VoiceChatHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: WebSocket handler for voice chat with authentication support.
---

# VoiceChatHandler

Defined in [`parrot.voice.handler`](../summaries/mod:parrot.voice.handler.md).

```python
class VoiceChatHandler
```

WebSocket handler for voice chat with authentication support.

Features:
- Pre-connection auth via Sec-WebSocket-Protocol header
- Post-connection auth via 'auth' message type
- Configurable route setup
- Heartbeat/ping mechanism

Authentication Methods:

1. Sec-WebSocket-Protocol (recommended for browsers):
   ```javascript
   // Frontend
   const ws = new WebSocket(url, ["jwt", token]);
   ```

2. Query parameter:
   ```javascript
   const ws = new WebSocket(`${url}?token=${token}`);
   ```

3. Post-connection message:
   ```javascript
   ws.send(JSON.stringify({type: "auth", token: "..."}));
   ```

Usage:
    handler = VoiceChatHandler(
        bot_factory=lambda: create_voice_bot(name="Assistant"),
        require_auth=True,
    )

    # Option 1: Setup routes
    handler.setup_routes(app, prefix="/api/v1")

    # Option 2: Direct route
    app.router.add_get('/ws/voice', handler.handle_websocket)

## Methods

- `def resolve_provider_client(provider: 'VoiceProvider')` — Resolve the ``AbstractClient`` subclass for *provider* (FEAT-302).
- `def setup_routes(self, app: web.Application, prefix: str='', *, include_health: bool=True, include_static: bool=True, static_dir: Optional[str]=None) -> None` — Register routes on an aiohttp application.
- `async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse` — Main WebSocket handler.
- `async def broadcast(self, message: Dict[str, Any]) -> None` — Send message to all active connections.
- `def active_connections(self) -> int` — Number of active connections.
