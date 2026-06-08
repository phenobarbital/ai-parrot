---
id: F007
query_id: Q011
type: read
intent: Identify the WS handler that serves voice so a new AgentTalk voice endpoint can register alongside it
executed_at: 2026-06-08T23:38:00Z
depth: 0
---

# F007 — `VoiceChatHandler` is a complete aiohttp WS shell, but hard-wired to the Gemini-Live `VoiceBot`

## Summary

`parrot/voice/handler.py` already provides `VoiceChatHandler` (a full aiohttp
WebSocket handler): JWT/anonymous auth (`TokenValidator`, three auth modes),
per-connection sessions, recording lifecycle, ping/heartbeat, route setup, and
`_handle_audio_data` that **base64-decodes inbound audio chunks** into a buffer
or a streaming queue. The session, auth, and message-routing scaffolding is
exactly what the AgentTalk voice feature needs. **The gap**: `bot_factory`
defaults to `create_voice_bot()` → a Gemini-Live `VoiceBot`, and audio is routed
into a native S2S session (`gemini_responding`, `audio_queue`) — not into
STT→text-Agent→TTS. So this feature either adds a "pipeline" mode to this handler
or ships a sibling handler reusing its transport/auth/session pieces.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
  lines: 293-396
  symbol: `VoiceChatHandler.__init__` / `_default_bot_factory`
  excerpt: |
    def __init__(self, bot_factory: Optional[Callable[[], VoiceBot]] = None, ...):
        self.bot_factory = bot_factory or self._default_bot_factory
    def _default_bot_factory(self) -> VoiceBot:
        return create_voice_bot(**config.as_dict())

- path: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
  lines: 993-1022
  symbol: `_handle_audio_data`
  excerpt: |
    if audio_b64 := message.get("data", ""):
        audio_bytes = base64.b64decode(audio_b64)
        if connection.streaming_mode == "streaming":
            await connection.audio_queue.put(audio_bytes)
        else:
            connection.audio_buffer += audio_bytes

- path: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
  lines: 521,642,795,923,1024
  symbol: `handle_websocket`, `_handle_message`, `_handle_start_session`, `_handle_start_recording`, `_handle_send_text`

## Notes

`bot_factory: Callable[[], VoiceBot]` is typed to VoiceBot — supporting a text
Agent + synthesizer means generalizing the factory/dispatch or a parallel class.
