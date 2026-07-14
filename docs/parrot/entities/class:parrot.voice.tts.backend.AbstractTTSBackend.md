---
type: Wiki Entity
title: AbstractTTSBackend
id: class:parrot.voice.tts.backend.AbstractTTSBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for text-to-speech synthesis backends.
---

# AbstractTTSBackend

Defined in [`parrot.voice.tts.backend`](../summaries/mod:parrot.voice.tts.backend.md).

```python
class AbstractTTSBackend(ABC)
```

Abstract base class for text-to-speech synthesis backends.

All TTS backends must implement the ``synthesize`` method. The optional
``close`` method may be overridden to release held resources (network
connections, loaded models, etc.).

Example::

    class MyBackend(AbstractTTSBackend):
        async def synthesize(self, text, *, voice=None, mime_format="audio/ogg"):
            audio_bytes = await my_tts_api(text, voice=voice)
            return SynthesisResult(audio=audio_bytes, mime_format=mime_format)

    backend = MyBackend()
    result = await backend.synthesize("Hello, world!")
    await backend.close()

## Methods

- `async def synthesize(self, text: str, *, voice: Optional[str]=None, mime_format: str='audio/ogg', language: Optional[str]=None) -> SynthesisResult` — Synthesize speech from text.
- `async def close(self) -> None` — Release resources held by the backend.
