---
type: Wiki Entity
title: SupertonicTTSBackend
id: class:parrot.voice.tts.supertonic_backend.SupertonicTTSBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: TTS backend that wraps the Supertonic ONNX speech model.
relates_to:
- concept: class:parrot.voice.tts.backend.AbstractTTSBackend
  rel: extends
---

# SupertonicTTSBackend

Defined in [`parrot.voice.tts.supertonic_backend`](../summaries/mod:parrot.voice.tts.supertonic_backend.md).

```python
class SupertonicTTSBackend(AbstractTTSBackend)
```

TTS backend that wraps the Supertonic ONNX speech model.

The ONNX inference session is created lazily on first ``synthesize`` call
to keep construction cheap (so ``VoiceSynthesizer._get_backend`` can build
the backend without paying the model-load cost). Inference runs in a worker
thread via ``asyncio.to_thread`` so the event loop is never blocked.

Args:
    voice: Default voice/speaker identifier to use when the caller does
        not supply one. ``None`` falls back to the Supertonic default
        speaker.
    model_path: Filesystem path to the Supertonic ONNX weights. When
        ``None`` (default), the ``SUPERTONIC_MODEL_PATH`` environment
        variable is consulted at synthesis time.
    sample_rate: Output PCM sample rate in Hz. Defaults to 44100 Hz
        (the actual Supertonic ONNX pipeline output rate).
    **kwargs: Extra keyword arguments are accepted and ignored to allow
        forward-compatible construction.

Example::

    backend = SupertonicTTSBackend(voice="default")
    result = await backend.synthesize("Hola, ¿en qué puedo ayudarte?")
    # result.audio is a playable WAV; result.mime_format == "audio/wav"
    await backend.close()

## Methods

- `async def synthesize(self, text: str, *, voice: Optional[str]=None, mime_format: str='audio/ogg', language: Optional[str]=None) -> SynthesisResult` — Synthesize speech from text using Supertonic.
- `async def close(self) -> None` — Release the ONNX inference session.
