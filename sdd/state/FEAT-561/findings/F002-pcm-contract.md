---
id: F002
query_id: Q009
type: read
intent: Nova and LiveAvatar have matching output formats
executed_at: 2026-09-07T05:42:49.930842+00:00
parent_id: null
depth: 1
---

# F002 — Nova and LiveAvatar have matching output formats

## Summary

NovaAudio uses 16000 Hz input and 24000 Hz output, mono 16-bit LPCM. It decodes base64 audio into LiveVoiceResponse.audio_data, yields interruption markers and breaks at completionEnd. VoiceSession provides sequential turn lifecycle, format preflight and reconnect handling; continuous RTC input is not needed for the clarified output-only scope.

## Citations

- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`
  lines: 303-305,633-657,1119-1177,1237-1249
  symbol: `NovaAudio`

- path: `packages/ai-parrot/src/parrot/voice/session.py`
  lines: 36-250,297-346
  symbol: `VoiceSession`
