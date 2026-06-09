---
id: F001
query_id: Q001
type: read
intent: Understand the existing voice bot abstraction and whether it already does STT->LLM->TTS
executed_at: 2026-06-08T23:32:00Z
depth: 0
---

# F001 — VoiceBot is native speech-to-speech (Gemini Live), NOT a discrete STT→LLM→TTS pipeline

## Summary

`VoiceBot` (771 lines) is built entirely around the **Gemini Live API** (native
speech-to-speech). It delegates STT+LLM+TTS to `GeminiLiveClient` in a single
streaming session — there is no decoupled "transcribe → run text agent → take
the structured answer → synthesize with an arbitrary TTS" path. Its outputs are
`LiveVoiceResponse` (raw `text` + `audio_data`), not the AgentTalk `AIMessage`
with `response`/`output`/`data`. So it does **not** satisfy the request (which
needs the structured agent answer + a swappable sub-second TTS like Supertonic).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/voice.py`
  lines: 21-33
  symbol: import block
  excerpt: |
    from ..clients.live import (
        GeminiLiveClient, LiveVoiceResponse, LiveCompletionUsage, GoogleVoiceModel,
    )
    from ..models.voice import VoiceConfig, AudioFormat

- path: `packages/ai-parrot/src/parrot/bots/voice.py`
  lines: 518-571
  symbol: `ask_voice`
  excerpt: |
    async def ask_voice(self, audio_input: bytes, ...) -> LiveVoiceResponse:
        # streams from self.ask_stream -> GeminiLiveClient; accumulates
        # full_text + full_audio. Returns LiveVoiceResponse(text, audio_data).

- path: `packages/ai-parrot/src/parrot/bots/voice.py`
  lines: 223-256
  symbol: `ask_text`
  excerpt: |
    # text path is hardcoded to GoogleGenAIClient (gemini-2.5-flash); not the
    # AgentTalk Agent pipeline.

## Notes

VoiceBot/Gemini Live is the "native voice↔voice" channel that FEAT-213
**explicitly deferred** (see F006). The requested feature is the *other* path.
