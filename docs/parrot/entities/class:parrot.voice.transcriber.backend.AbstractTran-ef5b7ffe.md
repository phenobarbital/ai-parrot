---
type: Wiki Entity
title: AbstractTranscriberBackend
id: class:parrot.voice.transcriber.backend.AbstractTranscriberBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for transcription backends.
---

# AbstractTranscriberBackend

Defined in [`parrot.voice.transcriber.backend`](../summaries/mod:parrot.voice.transcriber.backend.md).

```python
class AbstractTranscriberBackend(ABC)
```

Abstract base class for transcription backends.

This defines the interface that all transcription backends must implement.
The `transcribe` method is abstract and must be implemented by subclasses.
The `close` method has a default no-op implementation.

Example usage::

    class MyBackend(AbstractTranscriberBackend):
        async def transcribe(self, audio_path, language=None):
            # Implementation here
            return TranscriptionResult(...)

    backend = MyBackend()
    result = await backend.transcribe(Path("/path/to/audio.wav"))
    await backend.close()

## Methods

- `async def transcribe(self, audio_path: Path, language: Optional[str]=None) -> TranscriptionResult` — Transcribe audio file to text.
- `async def close(self) -> None` — Release resources held by the backend.
