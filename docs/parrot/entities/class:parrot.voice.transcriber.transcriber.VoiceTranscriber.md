---
type: Wiki Entity
title: VoiceTranscriber
id: class:parrot.voice.transcriber.transcriber.VoiceTranscriber
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Voice transcription service.
---

# VoiceTranscriber

Defined in [`parrot.voice.transcriber.transcriber`](../summaries/mod:parrot.voice.transcriber.transcriber.md).

```python
class VoiceTranscriber
```

Voice transcription service.

Manages transcription backend lifecycle and provides
a unified interface for transcribing audio files and URLs.

The backend is lazily created on first use. Use `close()` to
release backend resources when done.

Args:
    config: Configuration for the transcriber, including backend
        selection, model size, language, and duration limits.

Example::

    config = VoiceTranscriberConfig(
        backend=TranscriberBackend.FASTER_WHISPER,
        model_size="small",
        max_audio_duration_seconds=60,
    )
    transcriber = VoiceTranscriber(config)
    try:
        result = await transcriber.transcribe_url(
            url="https://teams.microsoft.com/files/voice.ogg",
            auth_token="Bearer xyz"
        )
        print(f"Transcription: {result.text}")
    finally:
        await transcriber.close()

## Methods

- `async def transcribe_file(self, file_path: Path, language: Optional[str]=None) -> TranscriptionResult` — Transcribe a local audio file.
- `async def transcribe_url(self, url: str, auth_token: Optional[str]=None, language: Optional[str]=None) -> TranscriptionResult` — Download and transcribe audio from URL.
- `async def close(self) -> None` — Release backend resources.
