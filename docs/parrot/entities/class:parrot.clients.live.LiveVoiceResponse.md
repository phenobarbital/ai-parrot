---
type: Wiki Entity
title: LiveVoiceResponse
id: class:parrot.clients.live.LiveVoiceResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Response from GeminiLiveClient voice interaction.
---

# LiveVoiceResponse

Defined in [`parrot.clients.live`](../summaries/mod:parrot.clients.live.md).

```python
class LiveVoiceResponse
```

Response from GeminiLiveClient voice interaction.

Enhanced version of VoiceResponse with CompletionUsage metadata
for consistency with other AbstractClient implementations.

## Methods

- `def to_websocket_message(self) -> Dict[str, Any]` — Format for WebSocket transmission.
