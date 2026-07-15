---
type: Wiki Entity
title: FasterWhisperBackend
id: class:parrot.voice.transcriber.faster_whisper_backend.FasterWhisperBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Local GPU-accelerated transcription using Faster Whisper.
relates_to:
- concept: class:parrot.voice.transcriber.backend.AbstractTranscriberBackend
  rel: extends
---

# FasterWhisperBackend

Defined in [`parrot.voice.transcriber.faster_whisper_backend`](../summaries/mod:parrot.voice.transcriber.faster_whisper_backend.md).

```python
class FasterWhisperBackend(AbstractTranscriberBackend)
```

Local GPU-accelerated transcription using Faster Whisper.

The model is loaded lazily on first transcription to save GPU memory.
Call `close()` to release the model when done.

Args:
    model_size: Whisper model size. Options: "tiny", "base", "small",
        "medium", "large-v3". Larger models are more accurate but slower.
        Default: "small" (good balance of speed and accuracy).
    device: Device to run on. Options: "cuda", "cpu", "auto".
        Default: "cuda" for GPU acceleration.
    compute_type: Precision for computation. Options: "float16", "int8",
        "float32". Default: "float16" for GPU (fastest with good accuracy).

Example::

    backend = FasterWhisperBackend(model_size="small")
    try:
        result = await backend.transcribe(Path("/path/to/audio.ogg"))
        print(f"Transcription: {result.text}")
    finally:
        await backend.close()  # Release GPU memory

## Methods

- `async def transcribe(self, audio_path: Path, language: Optional[str]=None) -> TranscriptionResult` — Transcribe audio file to text using Faster Whisper.
- `async def close(self) -> None` — Release the model and free GPU memory.
