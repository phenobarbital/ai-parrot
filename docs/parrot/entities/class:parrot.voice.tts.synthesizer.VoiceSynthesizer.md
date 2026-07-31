---
type: Wiki Entity
title: VoiceSynthesizer
id: class:parrot.voice.tts.synthesizer.VoiceSynthesizer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Text-to-speech synthesis service.
---

# VoiceSynthesizer

Defined in [`parrot.voice.tts.synthesizer`](../summaries/mod:parrot.voice.tts.synthesizer.md).

```python
class VoiceSynthesizer
```

Text-to-speech synthesis service.

Manages the TTS backend lifecycle and provides a unified interface for
synthesizing speech from text strings.

The backend is lazily created on first use. Call ``close()`` to release
backend resources when done.

Args:
    config: TTS configuration including backend selection, voice, and
        audio format. Defaults to ``TTSConfig()`` (Google backend,
        ``"audio/ogg"`` output) when ``None``.

Example::

    synth = VoiceSynthesizer(TTSConfig(backend="google", voice="Charon"))
    try:
        result = await synth.synthesize("Hello from the bot!")
        # result.audio holds the raw audio bytes
    finally:
        await synth.close()

## Methods

- `async def synthesize(self, text: str, *, language: Optional[str]=None) -> SynthesisResult` — Synthesize speech from text.
- `async def close(self) -> None` — Release backend resources.
