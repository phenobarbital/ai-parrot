---
type: Wiki Summary
title: parrot.voice.handler
id: mod:parrot.voice.handler
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: VoiceChatHandler - WebSocket Handler with Authentication
relates_to:
- concept: class:parrot.voice.handler.BotConfig
  rel: defines
- concept: class:parrot.voice.handler.VoiceChatHandler
  rel: defines
- concept: class:parrot.voice.handler.WebSocketConnection
  rel: defines
- concept: func:parrot.voice.handler.create_voice_server
  rel: defines
- concept: func:parrot.voice.handler.resolve_voice_client_class
  rel: defines
- concept: mod:parrot.bots.voice
  rel: references
- concept: mod:parrot.clients.live
  rel: references
- concept: mod:parrot.clients.nova_sonic
  rel: references
- concept: mod:parrot.core.ws_auth
  rel: references
- concept: mod:parrot.integrations.liveavatar
  rel: references
- concept: mod:parrot.integrations.liveavatar.optin
  rel: references
- concept: mod:parrot.models.voice
  rel: references
- concept: mod:parrot.voice.models
  rel: references
---

# `parrot.voice.handler`

VoiceChatHandler - WebSocket Handler with Authentication

Enhanced WebSocket handler for voice chat with:
- JWT authentication via Sec-WebSocket-Protocol (pre-connection)
- JWT authentication via message type (post-connection)
- Configurable route setup via setup_routes()
- Heartbeat/ping mechanism

This handler ONLY handles WebSocket transport.
It does NOT know about Google/Gemini - all voice logic
is encapsulated in VoiceBot/GeminiLiveClient.

## Classes

- **`BotConfig`** — Configuration for VoiceBot creation.
- **`WebSocketConnection`** — Represents an active WebSocket connection with auth state.
- **`VoiceChatHandler`** — WebSocket handler for voice chat with authentication support.

## Functions

- `def resolve_voice_client_class(provider: 'VoiceProvider')` — Resolve the ``AbstractClient`` subclass for a given ``VoiceProvider``.
- `def create_voice_server(bot_factory: Optional[Callable[[], VoiceBot]]=None, bot_config: Optional[Union[BotConfig, Dict[str, Any]]]=None, *, require_auth: bool=False, secret_key: Optional[str]=None, static_dir: Optional[str]=None, **kwargs) -> web.Application` — Create complete voice server application.
