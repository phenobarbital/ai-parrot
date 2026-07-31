---
type: Wiki Entity
title: GoogleTTSBackend
id: class:parrot.voice.tts.google_backend.GoogleTTSBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: TTS backend that wraps ``GoogleGenAIClient.generate_speech``.
relates_to:
- concept: class:parrot.voice.tts.backend.AbstractTTSBackend
  rel: extends
---

# GoogleTTSBackend

Defined in [`parrot.voice.tts.google_backend`](../summaries/mod:parrot.voice.tts.google_backend.md).

```python
class GoogleTTSBackend(AbstractTTSBackend)
```

TTS backend that wraps ``GoogleGenAIClient.generate_speech``.

Builds a ``SpeechGenerationPrompt`` with a single ``SpeakerConfig``
and calls ``generate_speech``; then extracts the raw audio bytes from
the returned ``AIMessage.output``.

Args:
    client: An already-instantiated ``GoogleGenAIClient``. When
        ``None`` (default), a new client is created lazily on first
        use. Providing an explicit client is the recommended pattern
        for unit testing (dependency injection).
    voice: Default voice identifier to use when the caller does not
        supply one (e.g. ``"Charon"``, ``"Kore"``, ``"Puck"``).
        Falls back to ``"Charon"`` when ``None``.
    **kwargs: Extra keyword arguments are accepted and ignored to
        allow forward-compatible construction.

Example::

    backend = GoogleTTSBackend(voice="Kore")
    result = await backend.synthesize("Hello, world!")
    print(f"Audio: {len(result.audio)} bytes, format: {result.mime_format}")

## Methods

- `async def synthesize(self, text: str, *, voice: Optional[str]=None, mime_format: str='audio/ogg', language: Optional[str]=None) -> SynthesisResult` — Synthesize speech from text using the Google TTS API.
- `async def close(self) -> None` — Release backend resources.
