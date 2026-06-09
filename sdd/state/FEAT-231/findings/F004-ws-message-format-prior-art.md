---
id: F004
query_id: Q005
type: read
intent: Read clients/live.py to see if realtime STT/TTS exists and the WS audio message format
executed_at: 2026-06-08T23:35:00Z
depth: 0
---

# F004 — `LiveVoiceResponse.to_websocket_message()` is the existing audio-over-WS payload convention

## Summary

`clients/live.py` (1347 lines) holds `GeminiLiveClient` and the
`LiveVoiceResponse` dataclass, which already defines a WebSocket serialization:
a JSON message with `type`, `text`, **`audio_base64`** (b64 of the audio bytes),
`audio_format`, `is_complete`, `tool_calls`, `usage`, `session_id`, `turn_id`.
This is the precedent to mirror for the AgentTalk voice reply (add a structured
`content`/`output` field alongside `audio_base64`).

## Citations

- path: `packages/ai-parrot/src/parrot/clients/live.py`
  lines: 189-213
  symbol: `LiveVoiceResponse.to_websocket_message`
  excerpt: |
    return {
        "type": "voice_response",
        "text": self.text,
        "audio_base64": base64.b64encode(self.audio_data).decode() if self.audio_data else None,
        "audio_format": self.audio_format,
        "is_complete": self.is_complete,
        "tool_calls": [tc.to_dict() for tc in self.tool_calls],
        "usage": {...}, "session_id": self.session_id, "turn_id": self.turn_id,
    }

## Notes

Audio is shipped base64-in-JSON over the WS, not as binary frames — consistent
with `_handle_audio_data` (F008) which b64-decodes inbound chunks.
