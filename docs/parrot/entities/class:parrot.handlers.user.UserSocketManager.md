---
type: Wiki Entity
title: UserSocketManager
id: class:parrot.handlers.user.UserSocketManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: WebSocket Manager with Redis PubSub integration for per-user interactions.
---

# UserSocketManager

Defined in [`parrot.handlers.user`](../summaries/mod:parrot.handlers.user.md).

```python
class UserSocketManager(WebSocketManager)
```

WebSocket Manager with Redis PubSub integration for per-user interactions.

Features:
- JWT authentication via msg_type="auth"
- Configurable channel subscriptions
- User info storage in Redis
- Geolocation tracking
- Direct messaging between users

Usage:
```python
from aiohttp import web
from parrot.handlers.user import UserSocketManager

app = web.Application()
ws_manager = UserSocketManager(
    app,
    redis_url="redis://localhost:6379/4",
    default_channels=["information", "following", "alerts"]
)

# Optional: Register a custom message callback
async def custom_handler(ws, channel, msg_type, content, username, client_info):
    logging.getLogger(__name__).debug("Custom message from %s: %s", username, content)
    return True  # Return True to indicate message was handled

ws_manager.register_message_handler(custom_handler)
```

## Methods

- `def register_message_handler(self, handler: Callable)` — Register a custom message handler callback.
- `async def broadcast_to_channel(self, channel: str, message: Dict[str, Any], exclude_ws: Optional[web.WebSocketResponse]=None)` — Broadcast a message to all subscribers of a channel.
- `async def broadcast_to_all(self, message: Dict[str, Any], exclude_ws: Optional[web.WebSocketResponse]=None)` — Broadcast a message to all authenticated users.
- `async def send_direct_message(self, from_username: str, to_username: str, content: Any) -> bool` — Send a direct message to a specific user.
- `def get_user_by_username(self, username: str) -> Optional[web.WebSocketResponse]` — Get WebSocket for a user by username.
- `def get_online_users(self) -> List[str]` — Get list of all online usernames.
- `async def user_geolocation(self, username: str, latitude: float, longitude: float)` — Process and store user geolocation update.
- `async def get_user_location(self, username: str) -> Optional[Dict[str, Any]]` — Get stored location for a user.
- `async def on_connect(self, ws: web.WebSocketResponse, channel: str, client_info: Dict[str, Any], session: Any)` — Handle new WebSocket connection.
- `async def on_message(self, ws: web.WebSocketResponse, channel: str, msg_type: str, msg_content: Any, username: str, client_info: Dict[str, Any], session: Any)` — Handle incoming WebSocket messages.
- `async def on_disconnect(self, ws: web.WebSocketResponse, channel: str, client_info: Dict[str, Any])` — Handle client disconnection.
- `async def notify_channel(self, channel_name: str, message: Dict[str, Any]) -> bool` — Send a notification to a specific channel (for external use by AgentTalk).
