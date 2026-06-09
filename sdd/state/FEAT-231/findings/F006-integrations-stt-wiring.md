---
id: F006
query_id: Q010
type: grep
intent: Find how integrations transcribe incoming audio (STT entrypoint) to reuse for WS audio
executed_at: 2026-06-08T23:37:00Z
depth: 0
---

# F006 — The "audio in → transcribe → run agent" pattern is already proven in MSTeams/Telegram wrappers

## Summary

Both the MSTeams and Telegram wrappers already implement the inbound half:
download audio → `VoiceTranscriber.transcribe_url(...)` → feed transcribed text
to the agent via a `_process_transcribed_message(...)` helper, gated by a
`voice_config`/`voice_enabled` flag. The STT step (FEAT-039) is centralized in
`parrot.voice.transcriber` and re-exported by integrations as thin shims. A WS
handler can call the same `VoiceTranscriber` on the decoded audio buffer.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 696-805
  symbol: `handle voice attachment` / `_process_transcribed_message`
  excerpt: |
    result = await self._voice_transcriber.transcribe_url(...)
    transcribed_text = result.text.strip()
    await self._process_transcribed_message(..., transcribed_text, ...)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/voice/__init__.py`
  lines: 10-14
  excerpt: |
    `parrot.voice.transcriber` (FEAT-039) for sharing across integrations.
    from parrot.voice.transcriber import (...)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/parser.py`
  lines: 140
  excerpt: |
    audio_extensions = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'}

## Notes

`transcribe_url` is URL-based; a WS handler holds raw bytes, so it needs the
buffer-based `transcribe(...)` entrypoint (already present on VoiceTranscriber).
