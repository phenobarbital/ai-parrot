---
type: Wiki Entity
title: VoiceChunk
id: class:parrot.voice.models.VoiceChunk
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Represents a chunk of audio data in a voice stream.
---

# VoiceChunk

Defined in [`parrot.voice.models`](../summaries/mod:parrot.voice.models.md).

```python
class VoiceChunk
```

Represents a chunk of audio data in a voice stream.

Can be used for both input (user speech) and output (agent speech).

## Methods

- `def to_base64(self) -> str` — Encode audio data to base64 for WebSocket transmission.
- `def from_base64(cls, b64_data: str, format: AudioFormat=AudioFormat.PCM_16K) -> 'VoiceChunk'` — Create VoiceChunk from base64 encoded data.
- `def duration_ms(self) -> float` — Estimate duration in milliseconds based on format and data size.
