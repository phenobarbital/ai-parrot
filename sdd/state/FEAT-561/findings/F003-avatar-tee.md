---
id: F003
query_id: Q010
type: read
intent: VoiceChat already forwards generated audio to a LITE avatar
executed_at: 2026-09-07T05:42:49.930842+00:00
parent_id: null
depth: 1
---

# F003 — VoiceChat already forwards generated audio to a LITE avatar

## Summary

VoiceChatHandler stores the avatar session on WebSocketConnection.avatar_session. _HandlerVoiceSession._relay first sends browser frames, then awaits avatar audio/end/interrupt operations with caught errors. The older _send_voice_response has a parallel tee. Startup returns audio=dual. These are existing code paths, not evidence of a live Nova/avatar test; a slow avatar send can delay subsequent relay work despite exception isolation.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
  lines: 254-256,510-537,1151-1196,1631-1686,1688-1717,1791-1804
  symbol: `_HandlerVoiceSession._relay`

- path: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
  lines: 586-644
  symbol: `VoiceChatHandler`

- path: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py`
  lines: 151-250
  symbol: `VoiceAvatarSession`
