---
type: Wiki Entity
title: TranscriberBackend
id: class:parrot.voice.transcriber.models.TranscriberBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Available transcription backends.
---

# TranscriberBackend

Defined in [`parrot.voice.transcriber.models`](../summaries/mod:parrot.voice.transcriber.models.md).

```python
class TranscriberBackend(str, Enum)
```

Available transcription backends.

- FASTER_WHISPER: Local GPU-accelerated transcription using faster-whisper
- OPENAI_WHISPER: Cloud-based transcription using OpenAI Whisper API
- MOONSHINE: Opt-in sub-second local transcription using Moonshine ONNX
  models (added in FEAT-231)
