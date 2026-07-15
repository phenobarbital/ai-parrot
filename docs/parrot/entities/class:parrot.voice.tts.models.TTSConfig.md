---
type: Wiki Entity
title: TTSConfig
id: class:parrot.voice.tts.models.TTSConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for text-to-speech synthesis.
---

# TTSConfig

Defined in [`parrot.voice.tts.models`](../summaries/mod:parrot.voice.tts.models.md).

```python
class TTSConfig(BaseModel)
```

Configuration for text-to-speech synthesis.

Controls which backend to use and the audio output format.
All fields are optional; defaults produce a Google TTS backend
with OGG/Opus output (the preferred format for Telegram voice notes).

Attributes:
    backend: TTS backend to use. Currently only ``"google"`` is
        implemented; ``"elevenlabs"`` and ``"openai"`` are reserved
        for future use and will raise ``ValueError`` at runtime.
    voice: Backend-specific voice identifier (e.g. ``"Charon"``,
        ``"Kore"`` for the Google backend). ``None`` falls back to
        the backend's default voice.
    language: BCP-47 language tag (e.g. ``"en-US"``). ``None``
        delegates language selection to the backend.
    mime_format: MIME type of the desired audio output. Telegram
        voice notes prefer ``"audio/ogg"`` (OGG/Opus).
    total_step: Supertonic only — number of flow-matching denoising
        steps. Higher is smoother but slower; ignored by other backends.
    speed: Supertonic only — speech-rate multiplier (``>1`` = faster);
        ignored by other backends.

Example::

    cfg = TTSConfig(backend="google", voice="Charon", language="en-US")
    cfg = TTSConfig(backend="supertonic", voice="F1", total_step=8, speed=1.05)
