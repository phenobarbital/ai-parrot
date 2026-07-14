---
type: Wiki Entity
title: WebHumanChannel
id: class:parrot.human.channels.web.WebHumanChannel
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Human channel that delivers interactions via WebSocket.
relates_to:
- concept: class:parrot.human.channels.base.HumanChannel
  rel: extends
---

# WebHumanChannel

Defined in [`parrot.human.channels.web`](../summaries/mod:parrot.human.channels.web.md).

```python
class WebHumanChannel(HumanChannel)
```

Human channel that delivers interactions via WebSocket.

Translates :class:`~parrot.human.models.HumanInteraction` objects into
JSON payloads of type ``hitl:question`` and publishes them to the
WebSocket channel identified by the ``recipient`` argument (which is
typically the user's ``session_id``).

Args:
    socket_manager: The :class:`~parrot.handlers.user.UserSocketManager`
        instance used to publish messages to WebSocket channels.

Attributes:
    channel_type: Identifier for this channel type, fixed to ``"web"``.

## Methods

- `async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool` — Serialize an interaction and push it to the user's WebSocket channel.
- `async def register_response_handler(self, callback: Callable[[HumanResponse], Awaitable[None]]) -> None` — Store the response callback registered by the manager.
- `async def send_notification(self, recipient: str, message: str) -> None` — Send a plain notification message to a WebSocket channel.
- `async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool` — Emit a cancellation payload to the user's WebSocket channel.
