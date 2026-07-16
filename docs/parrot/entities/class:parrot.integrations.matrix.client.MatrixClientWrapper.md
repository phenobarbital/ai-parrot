---
type: Wiki Entity
title: MatrixClientWrapper
id: class:parrot.integrations.matrix.client.MatrixClientWrapper
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async wrapper around mautrix Client for AI-Parrot operations.
---

# MatrixClientWrapper

Defined in [`parrot.integrations.matrix.client`](../summaries/mod:parrot.integrations.matrix.client.md).

```python
class MatrixClientWrapper
```

Async wrapper around mautrix Client for AI-Parrot operations.

Handles connection lifecycle, message sending, message editing
(for streaming), room state management, and event listening.

## Methods

- `async def connect(self) -> None` — Connect to the homeserver and start syncing.
- `async def start_sync(self) -> None` — Start the /sync loop in background.
- `async def disconnect(self) -> None` — Stop syncing and close the client.
- `def client(self) -> MautrixClient` — Access the underlying mautrix Client (for event handler registration).
- `def mxid(self) -> str` — Return the bot's Matrix ID.
- `async def send_text(self, room_id: str, text: str, *, html: Optional[str]=None, msg_type: str='m.text') -> str` — Send a text message to a room.
- `async def edit_message(self, room_id: str, original_event_id: str, new_text: str, *, new_html: Optional[str]=None) -> str` — Edit a previously sent message (used for streaming).
- `async def send_event(self, room_id: str, event_type: str, content: Dict[str, Any]) -> str` — Send a custom message event to a room.
- `async def set_room_state(self, room_id: str, event_type: str, content: Dict[str, Any], state_key: str='') -> str` — Set a state event in a room.
- `async def get_room_state_event(self, room_id: str, event_type: str, state_key: str='') -> Optional[Dict[str, Any]]` — Read a state event from a room.
- `def on_message(self, callback: Callable[..., Coroutine[Any, Any, None]]) -> None` — Register a handler for m.room.message events.
- `def on_custom_event(self, event_type: str, callback: Callable[..., Coroutine[Any, Any, None]]) -> None` — Register a handler for a custom event type.
