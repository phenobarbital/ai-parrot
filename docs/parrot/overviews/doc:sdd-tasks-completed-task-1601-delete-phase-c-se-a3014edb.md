---
type: Wiki Overview
title: 'TASK-1601: Delete Phase C server endpoints + dispatch + voice_start/stop'
id: doc:sdd-tasks-completed-task-1601-delete-phase-c-server-endpoints-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'With the Phase C worker gone (TASK-1600), its server-side entry points are
  dead:'
---

# TASK-1601: Delete Phase C server endpoints + dispatch + voice_start/stop

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1600
**Assigned-to**: unassigned

---

## Context

With the Phase C worker gone (TASK-1600), its server-side entry points are dead:
the `/voice-native/start` endpoint, the FEAT-244 `voice_start`/`voice_stop`
control messages on `StreamHandler`, and the LiveKit worker-dispatch helpers.
Remove them. KEEP the LITE avatar endpoints and plain text streaming.
(Spec §3.1.)

---

## Scope

- In `handlers/avatar.py`: delete `_start_voice_native_session`,
  `VoiceNativeAvatarView`, `start_voice_native`, `stop_voice_native`, and their
  route registration in `register_avatar_routes`. **KEEP** `_start_avatar_session`,
  `_stop_avatar_session`, `AvatarSessionView`, `close_all_avatar_sessions` (LITE).
- In `handlers/stream.py`: delete `voice_start` / `voice_stop` handlers,
  `_ws_voice_sessions`, and the avatar-specific channel-subscription /
  `broadcast_to_channel` plumbing added by FEAT-244. **KEEP** SSE/WS/NDJSON/
  chunked text streaming and `app['stream_handler']` wiring.
- In `liveavatar/room_manager.py`: delete `dispatch_worker`, `delete_dispatch`,
  `mint_browser_token` (publish-audio token, Phase C). **KEEP** `mint_room_tokens`
  (LITE + Mode C viewer tokens).
- In `manager/manager.py`: remove the `/voice-native/start` registration path
  inside `_register_avatar_routes` (keep LITE registration).
- Delete/trim the corresponding Phase-C tests.

**NOT in scope**: the Redis transport rename (TASK-1603); `_setup_liveavatar_voice`
gate rename (TASK-1603); other dead code (TASK-1602).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/avatar.py` | MODIFY | remove voice-native parts (~`:286-486`, `VoiceNativeAvatarView` ~`:475`), keep LITE |
| `packages/ai-parrot-server/src/parrot/handlers/stream.py` | MODIFY | remove `voice_start`/`voice_stop` + `_ws_voice_sessions` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py` | MODIFY | remove dispatch_worker/delete_dispatch/mint_browser_token |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | drop `/voice-native/start` route |
| tests touching the above | MODIFY/DELETE | remove Phase C cases |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures / Anchors (verified)
```python
# handlers/avatar.py
#   _start_avatar_session :77   _stop_avatar_session :223   AvatarSessionView :455  (KEEP)
#   _start_voice_native_session / start_voice_native / stop_voice_native ~:286-486  (DELETE)
#   VoiceNativeAvatarView :475 ; route "/api/v1/agents/avatar/{agent_id}/voice-native/start" :546  (DELETE)
#   register_avatar_routes :519  (KEEP, minus voice-native route)
# handlers/stream.py
#   add_post '/bots/{bot_id}/stream/sse' :587 ... '/stream/ws' :596  (KEEP)
#   voice_start :378  voice_stop :428  _ws_voice_sessions  broadcast_to_channel :492  (DELETE voice bits)
# room_manager.py
#   mint_room_tokens :78  (KEEP)   mint_browser_token :138 / dispatch_worker :191 / delete_dispatch :244  (DELETE)
# manager/manager.py
#   _register_avatar_routes :1486 (KEEP) ; calls registering '/voice-native/start' (DELETE)
```

### Does NOT Exist (after this task)
- ~~`/api/v1/agents/avatar/{agent_id}/voice-native/start`~~ — route deleted
- ~~`voice_start` / `voice_stop` WS messages~~ — deleted
- ~~`room_manager.dispatch_worker` / `mint_browser_token`~~ — deleted

---

## Implementation Notes
- `avatar.py` interleaves LITE (keep) and Phase C (delete) — split carefully;
  run `pytest packages/ai-parrot-server/.../test_avatar_endpoint.py` after.
- Keep `app['stream_handler']` and `broadcast_to_channel` only if TASK-1603 still
  needs a StreamHandler arm — per spec the StreamHandler arm of `_FanOutSink` is
  dropped, so remove StreamHandler's avatar channel plumbing here.

---

## Acceptance Criteria
- [ ] No `voice-native`, `voice_start`, `voice_stop`, `dispatch_worker`, `mint_browser_token` references remain (non-test).
- [ ] LITE endpoints (`/avatar/{id}/start|stop`) and text streaming still register and pass their tests.
- [ ] `pytest packages/ai-parrot-server/src/parrot/handlers` (avatar + stream) green.

---

## Agent Instructions
Standard SDD flow.

## Completion Note
Implemented 2026-06-19. Deleted from avatar.py: `AVATAR_VOICE_SESSIONS_KEY`,
`_delete_voice_dispatch`, `_worker_agent_name`, `start_voice_native`, `stop_voice_native`,
`_start_voice_native_session`, `VoiceNativeAvatarView`, voice-native route in `register_avatar_routes`.
Rewrote stream.py removing `voice_start`/`voice_stop` handlers, `channel_subscriptions`,
`_ws_voice_sessions`, `_subscribe_to_channel`, `_unsubscribe_from_channel`,
`broadcast_to_channel`, `_cleanup_ws_voice_sessions`. Removed from room_manager.py:
`mint_browser_token`, `dispatch_worker`, `delete_dispatch`. Deleted Phase C server tests.
68 handler tests pass.
