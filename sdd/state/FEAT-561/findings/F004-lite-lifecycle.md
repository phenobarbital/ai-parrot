---
id: F004
query_id: Q011
type: read
intent: Existing LITE session and audio transport can be reused
executed_at: 2026-09-07T05:42:49.930842+00:00
parent_id: null
depth: 1
---

# F004 — Existing LITE session and audio transport can be reused

## Summary

VoiceAvatarSession mints a room named from session_id, passes publisher credentials to LiveAvatar, starts the session and opens the avatar WebSocket. Viewer credentials exclude publisher and vendor secrets; cleanup is idempotent. AvatarWebSocket uses agent.speak, agent.speak_end and agent.interrupt, with a connected gate; send_audio_frame slices each incoming buffer independently, without accumulating tiny chunks across calls.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py`
  lines: 151-270
  symbol: `VoiceAvatarSession`

- path: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/avatar_ws.py`
  lines: 153-228,283-305
  symbol: `AvatarWebSocket`

- path: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py`
  lines: 149-170
  symbol: `LiveAvatarClient.create_session_token`
