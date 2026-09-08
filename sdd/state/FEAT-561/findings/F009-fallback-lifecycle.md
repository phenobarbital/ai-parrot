---
id: F009
query_id: Q016
type: read
intent: Direct audio fallback exists in another session path
executed_at: 2026-09-07T05:42:49.930842+00:00
parent_id: null
depth: 1
---

# F009 — Direct audio fallback exists in another session path

## Summary

The REST avatar start path can start RoomAudioPublisher for avatar=false or no credits; the voice WebSocket startup instead degrades to browser voice-only. Observer fallback therefore needs explicit shared-room behavior. RoomAudioPublisher.start reuses tokens.agent_token; its flush only toggles a flag and yields, without clearing AudioSource queued samples. Simultaneous use with the avatar publisher would also reuse the fixed identity unless changed. REST stop pops a shared session record, so observers must not invoke it.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/avatar.py`
  lines: 151-188,216-240,344-367,435-465
  symbol: `_start_avatar_session`

- path: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_audio_publisher.py`
  lines: 138-153,170-236
  symbol: `RoomAudioPublisher`
