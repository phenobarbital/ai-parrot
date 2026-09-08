---
id: F005
query_id: Q012
type: read
intent: Multi-viewer token issuance exists but targets REST session state
executed_at: 2026-09-07T05:42:49.930842+00:00
parent_id: null
depth: 1
---

# F005 — Multi-viewer token issuance exists but targets REST session state

## Summary

_mint_viewer_tokens accepts 1-50 requested tokens per call, checks app AVATAR_SESSIONS_KEY for session_id, creates distinct viewer identities and returns only viewer credentials. This is a batch limit, not total audience capacity. VoiceAvatarSession is held separately on a WebSocket connection (F003); the examined paths do not register it in that REST store. mint_room_tokens creates subscribe-only viewer grants and a fixed avatar-agent publisher identity. Authentication decorators exist, but the helper checks session existence without matching agent_id, tenant or owner. Shared discovery must enforce those relationships rather than merely exposing a process-local dictionary.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/avatar.py`
  lines: 560-653,680-688
  symbol: `_mint_viewer_tokens`

- path: `packages/ai-parrot-server/src/parrot/handlers/avatar.py`
  lines: 643-653
  symbol: `AvatarViewersView`

- path: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py`
  lines: 64-135
  symbol: `LiveKitRoomManager.mint_room_tokens`
