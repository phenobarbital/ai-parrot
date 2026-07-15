---
type: Wiki Entity
title: SynthesisResult
id: class:parrot.voice.tts.models.SynthesisResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of a text-to-speech synthesis call.
---

# SynthesisResult

Defined in [`parrot.voice.tts.models`](../summaries/mod:parrot.voice.tts.models.md).

```python
class SynthesisResult(BaseModel)
```

Result of a text-to-speech synthesis call.

Contains the raw audio bytes and metadata about the synthesized audio.

Attributes:
    audio: Raw audio bytes as produced by the backend. The actual
        container format matches ``mime_format`` (e.g. WAV PCM bytes
        for ``"audio/wav"``).
    mime_format: MIME type of the audio data (e.g. ``"audio/wav"``,
        ``"audio/ogg"``).
    duration_s: Duration of the synthesized audio in seconds.
        ``None`` when not available from the backend.

Example::

    result = SynthesisResult(audio=b"...", mime_format="audio/ogg")
    assert result.duration_s is None  # not populated unless backend provides it
