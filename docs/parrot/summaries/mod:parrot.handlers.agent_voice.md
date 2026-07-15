---
type: Wiki Summary
title: parrot.handlers.agent_voice
id: mod:parrot.handlers.agent_voice
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP handler for voice agent interaction (FEAT-231).
relates_to:
- concept: class:parrot.handlers.agent_voice.AgentTranscribeOnly
  rel: defines
- concept: class:parrot.handlers.agent_voice.AgentVoiceTalk
  rel: defines
- concept: mod:parrot.handlers.agent
  rel: references
- concept: mod:parrot.integrations.liveavatar.optin
  rel: references
- concept: mod:parrot.voice.transcriber.models
  rel: references
- concept: mod:parrot.voice.transcriber.transcriber
  rel: references
- concept: mod:parrot.voice.tts.models
  rel: references
- concept: mod:parrot.voice.tts.synthesizer
  rel: references
---

# `parrot.handlers.agent_voice`

HTTP handler for voice agent interaction (FEAT-231).

``AgentVoiceTalk`` is a thin REST subclass of :class:`AgentTalk` that adds a
voice I/O adapter around the **unchanged** text dispatch:

    audio note  ──STT──▶  query: str  ──bot.ask()──▶  AIMessage
                                                          │
    audio + content  ◀──TTS──  AIMessage.response  ◀──────┘

It inherits agent resolution, PBAC, HITL, auth envelopes, session handling and
output negotiation from :class:`AgentTalk`, mirroring the existing
``InfographicTalk(AgentTalk)`` precedent, and overrides only the two voice
seams:

1. **Inbound (STT).** ``handle_upload`` is overridden: after the inherited
   multipart parse, an audio attachment (if present) is transcribed via a
   lazily-imported :class:`VoiceTranscriber` and the transcript is injected as
   ``data['query']`` so the inherited ``post()`` text path runs unchanged.
2. **Outbound (TTS).** ``post`` is overridden to wrap ``super().post()``: when
   the request carried voice input, ``AIMessage.response`` (str only) is
   synthesized via a lazily-imported :class:`VoiceSynthesizer` and
   ``audio_base64`` + ``audio_format`` are attached to the inherited JSON
   envelope. ``output`` / ``data`` / ``media`` stay in ``content`` and never
   pass through the synthesizer.

The voice stack (``parrot.voice.*``, shipped by ``ai-parrot-integrations``) is
imported **lazily inside the voice code path** so server boot never hard-requires
the satellite distribution. TTS failures degrade gracefully to text-only.

Added by FEAT-231 (AgentTalk Voice Support).

## Classes

- **`AgentVoiceTalk(AgentTalk)`** — Voice-capable REST handler: audio → STT → text agent → TTS → audio.
- **`AgentTranscribeOnly(AgentVoiceTalk)`** — Transcribe-only endpoint for Mode B internal STT (FEAT-249 TASK-1608).
