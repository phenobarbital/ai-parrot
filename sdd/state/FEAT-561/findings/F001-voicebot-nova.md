---
id: F001
query_id: Q008
type: read
intent: VoiceBot already selects Nova 2 Sonic and owns voice memory
executed_at: 2026-09-07T05:42:49.930842+00:00
parent_id: null
depth: 1
---

# F001 — VoiceBot already selects Nova 2 Sonic and owns voice memory

## Summary

VoiceBot resolves provider nova to NovaClient with default nova-2-sonic. Its ask_stream accepts audio chunks, delegates to stream_voice, and persists transcript turns through save_conversation_turn. The new output broadcast should preserve this bot-owned execution path.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/voice.py`
  lines: 190-258
  symbol: `VoiceBot._resolve_llm_config`

- path: `packages/ai-parrot/src/parrot/bots/voice.py`
  lines: 475-663
  symbol: `VoiceBot.ask_stream`
