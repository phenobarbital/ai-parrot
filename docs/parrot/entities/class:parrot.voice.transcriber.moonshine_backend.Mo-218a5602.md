---
type: Wiki Entity
title: MoonshineSTTBackend
id: class:parrot.voice.transcriber.moonshine_backend.MoonshineSTTBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Sub-second speech-to-text backend using the Moonshine ONNX models.
relates_to:
- concept: class:parrot.voice.transcriber.backend.AbstractTranscriberBackend
  rel: extends
---

# MoonshineSTTBackend

Defined in [`parrot.voice.transcriber.moonshine_backend`](../summaries/mod:parrot.voice.transcriber.moonshine_backend.md).

```python
class MoonshineSTTBackend(AbstractTranscriberBackend)
```

Sub-second speech-to-text backend using the Moonshine ONNX models.

The model is loaded lazily on first ``transcribe`` call to keep
construction cheap (so ``VoiceTranscriber._get_backend`` can build the
backend without paying the model-load cost). Inference runs in a worker
thread via ``asyncio.to_thread`` so the event loop is never blocked.

Args:
    model_name: Moonshine model identifier (``"moonshine/base"`` default
        or ``"moonshine/tiny"``).
    **kwargs: Extra keyword arguments are accepted and ignored to allow
        forward-compatible construction.

Example::

    backend = MoonshineSTTBackend(model_name="moonshine/base")
    try:
        result = await backend.transcribe(Path("/path/to/audio.wav"))
        print(result.text)
    finally:
        await backend.close()

## Methods

- `async def transcribe(self, audio_path: Path, language: Optional[str]=None) -> TranscriptionResult` — Transcribe an audio file to text using Moonshine.
- `async def close(self) -> None` — Release the Moonshine runtime reference.
