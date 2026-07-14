---
type: Wiki Summary
title: parrot.voice.transcriber.moonshine_backend
id: mod:parrot.voice.transcriber.moonshine_backend
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Moonshine STT Backend.
relates_to:
- concept: class:parrot.voice.transcriber.moonshine_backend.MoonshineSTTBackend
  rel: defines
- concept: mod:parrot.voice.transcriber.backend
  rel: references
- concept: mod:parrot.voice.transcriber.models
  rel: references
---

# `parrot.voice.transcriber.moonshine_backend`

Moonshine STT Backend.

Opt-in sub-second speech-to-text backend built on the Moonshine ONNX models.
Implements :class:`AbstractTranscriberBackend` so the :class:`VoiceTranscriber`
service can select it interchangeably with the default FasterWhisper backend.

Mirrors the structure of :class:`FasterWhisperBackend`: the model is loaded
lazily on first transcription and the CPU/GPU-bound inference runs off the
event loop via ``asyncio.to_thread``.

Opt-in only — FasterWhisper remains the default STT backend
(``VoiceTranscriberConfig.backend == TranscriberBackend.FASTER_WHISPER``).
The Moonshine runtime ships behind the
``ai-parrot-integrations[voice-moonshine]`` extra; when it is missing the
backend raises ``ImportError`` / ``RuntimeError``.

Added by FEAT-231 (AgentTalk Voice Support).

## Classes

- **`MoonshineSTTBackend(AbstractTranscriberBackend)`** — Sub-second speech-to-text backend using the Moonshine ONNX models.
