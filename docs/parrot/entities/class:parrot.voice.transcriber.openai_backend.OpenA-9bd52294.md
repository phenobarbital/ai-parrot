---
type: Wiki Entity
title: OpenAIWhisperBackend
id: class:parrot.voice.transcriber.openai_backend.OpenAIWhisperBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Cloud-based transcription using OpenAI Whisper API.
relates_to:
- concept: class:parrot.voice.transcriber.backend.AbstractTranscriberBackend
  rel: extends
---

# OpenAIWhisperBackend

Defined in [`parrot.voice.transcriber.openai_backend`](../summaries/mod:parrot.voice.transcriber.openai_backend.md).

```python
class OpenAIWhisperBackend(AbstractTranscriberBackend)
```

Cloud-based transcription using OpenAI Whisper API.

Requires an OpenAI API key. Supports automatic retry
with exponential backoff for rate limits.

Args:
    api_key: OpenAI API key (required).
    model: Whisper model to use. Default: "whisper-1".
    max_retries: Maximum number of retry attempts for rate limits.
        Default: 3.
    timeout_seconds: Request timeout in seconds. Default: 60.

Example::

    backend = OpenAIWhisperBackend(api_key="sk-...")
    try:
        result = await backend.transcribe(Path("/path/to/audio.ogg"))
        print(f"Transcription: {result.text}")
    finally:
        await backend.close()  # Release HTTP session

Raises:
    ValueError: If api_key is empty or None.

## Methods

- `async def transcribe(self, audio_path: Path, language: Optional[str]=None) -> TranscriptionResult` — Transcribe audio file to text using OpenAI Whisper API.
- `async def close(self) -> None` — Close the aiohttp session.
