---
type: Wiki Entity
title: VoiceResponse
id: class:parrot.voice.models.VoiceResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Response from a voice interaction.
---

# VoiceResponse

Defined in [`parrot.voice.models`](../summaries/mod:parrot.voice.models.md).

```python
class VoiceResponse
```

Response from a voice interaction.

Contains both text and audio components for multimodal output.

## Methods

- `def to_websocket_message(self) -> Dict[str, Any]` — Format response for WebSocket transmission.
