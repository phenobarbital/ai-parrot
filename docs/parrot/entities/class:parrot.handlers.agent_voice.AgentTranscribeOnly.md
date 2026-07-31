---
type: Wiki Entity
title: AgentTranscribeOnly
id: class:parrot.handlers.agent_voice.AgentTranscribeOnly
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Transcribe-only endpoint for Mode B internal STT (FEAT-249 TASK-1608).
relates_to:
- concept: class:parrot.handlers.agent_voice.AgentVoiceTalk
  rel: extends
---

# AgentTranscribeOnly

Defined in [`parrot.handlers.agent_voice`](../summaries/mod:parrot.handlers.agent_voice.md).

```python
class AgentTranscribeOnly(AgentVoiceTalk)
```

Transcribe-only endpoint for Mode B internal STT (FEAT-249 TASK-1608).

Exposes ``POST /api/v1/agents/transcribe/{agent_id}`` — accepts a multipart
audio upload, runs STT via :class:`VoiceTranscriber` (backend selectable via
``stt_backend`` form field), and returns ``{"text": "<transcript>"}`` without
invoking the agent.

This allows the FULL-mode frontend to obtain a transcript from ai-parrot's
internal STT (FasterWhisper or OpenAI Whisper) instead of relying on the
LiveAvatar data-channel ``user.transcription`` events.  LiveAvatar STT remains
the *documented default*; internal STT is opt-in via this endpoint.

Backend selection mirrors :meth:`AgentVoiceTalk._read_voice_options`:
    ``stt_backend=faster_whisper`` (local, default) or ``stt_backend=openai``
    (cloud).  Unknown values are logged and fall back to the configured default.

Returns:
    JSON ``{"text": "<transcript>"}`` on success.
    HTTP 503 when the voice stack (``ai-parrot-integrations[voice]``) is absent.
    HTTP 400 when transcription fails (e.g. bad audio, duration guard).

## Methods

- `async def post(self) -> web.Response` — Handle POST: parse multipart, transcribe audio, return transcript.
