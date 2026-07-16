---
type: Wiki Overview
title: 'TASK-1629: _start_avatar_session mode-select + 402 auto-fallback'
id: doc:sdd-tasks-completed-task-1629-start-session-mode-select-fallback-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 3 — the wiring that selects the audio mode and degrades gracefully.
---

# TASK-1629: _start_avatar_session mode-select + 402 auto-fallback

**Feature**: FEAT-256 — LiveKit Direct Audio (avatar-optional livekit voice)
**Spec**: `sdd/specs/livekit-direct-audio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1627, TASK-1628
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 — the wiring that selects the audio mode and degrades gracefully.
`_start_avatar_session` always starts a LiveAvatar session today. This task makes
it read an `avatar` flag, start the `RoomAudioPublisher` for the avatar-OFF mode,
and — crucially — **auto-fall back** to the publisher when LiveAvatar returns the
no-credits `402` (instead of returning the error). The active publisher is stored
in `AVATAR_SESSIONS_KEY` and torn down by `_stop_avatar_session`.

---

## Scope

- Accept an optional `avatar: bool` in the `/start` body (default **True** for back-compat).
- avatar-ON + credits → today's LiveAvatar path (unchanged).
- avatar-OFF → mint tokens, start `RoomAudioPublisher`, register it; speaker uses the
  room sink (TASK-1628).
- On the LiveAvatar `ClientResponseError` that `avatar_upstream_error_response` maps
  to no-credits (`402`/code 4033): **auto-fallback** → start the publisher, return a
  normal `{livekit_url, client_token, session_id}` (NOT the 402).
- Extend `_stop_avatar_session` to tear down the publisher when present.
- Unit tests for: avatar-off path, auto-fallback, avatar-on unchanged.

**NOT in scope**: publisher internals (1627), speaker routing (1628), the frontend flag.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/avatar.py` | MODIFY | mode select in `_start_avatar_session`; 402 auto-fallback; publisher teardown in `_stop_avatar_session` |
| `packages/ai-parrot-server/tests/.../test_avatar_start_modes.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# handlers/avatar.py
async def _start_avatar_session(request: web.Request) -> web.Response: ...
async def _stop_avatar_session(request: web.Request) -> web.Response: ...
AVATAR_SESSIONS_KEY                               # app store: {session_id: {...}}
def avatar_upstream_error_response(exc: ClientResponseError) -> web.Response
#   -> 402 {error:"avatar_no_credits"} | 502 ; this is the no-credits SIGNAL.
from aiohttp import web, ClientResponseError      # already imported

# mint_room_tokens(session_id, agent_id) -> LiveKitRoomTokens   (room_manager.py)
# RoomAudioPublisher.start(tokens, ...) / .aclose()             (TASK-1627)
```

### Does NOT Exist
- ~~an `avatar` flag in the `/start` body today~~ — add it (default True).
- ~~a publisher entry in `AVATAR_SESSIONS_KEY`~~ — store one for the avatar-OFF mode.

---

## Implementation Notes

### Key Constraints
- Mode is exclusive per session (avatar-ON XOR avatar-OFF). Never both → no double audio.
- The `402` detection must reuse the existing no-credits mapping, not re-parse.
- Teardown ordering: disconnect the publisher (room participant) cleanly to avoid
  orphaned LiveKit Cloud connection-minutes.
- Keep the existing keep-alive caveat (do NOT `async with` long-lived sessions).

### References in Codebase
- `handlers/avatar.py:_start_avatar_session` (current LiveAvatar flow + the
  `except ClientResponseError` block added for the 402 handler).

---

## Acceptance Criteria

- [ ] `avatar=false` → no LiveAvatar `start_session`; publisher started; 200 with creds.
- [ ] LiveAvatar `402` with `avatar=true` → auto-fallback to publisher; 200 (not 402).
- [ ] `avatar=true` + credits → unchanged LiveAvatar path.
- [ ] `/stop` tears down whichever publisher is active.
- [ ] Unit tests pass (`pytest packages/ai-parrot-server -k avatar_start_modes -v`).

---

## Test Specification
```python
async def test_start_avatar_off_uses_publisher(...): ...
async def test_start_402_autofalls_back(...): ...
async def test_start_avatar_on_unchanged(...): ...
```

---

## Completion Note

Modified `handlers/avatar.py`:

- Added `_is_no_credits_error(exc)` helper (reuses same 4033/credit detection as `avatar_upstream_error_response`).
- Added `_start_direct_audio_session(tokens, session_id, store)` shared helper: imports `RoomAudioPublisher` lazily, calls `start()`, stores `{"publisher": publisher}` in the session store.
- Updated `_start_avatar_session`: reads `avatar` bool (default True); avatar=False → calls `_start_direct_audio_session`; avatar=True + 402 no-credits → auto-fallback via `_start_direct_audio_session`; avatar=True + credits → unchanged LiveAvatar path.
- Updated `_stop_avatar_session`: detects `publisher` key → calls `publisher.aclose()`; otherwise existing `client.stop_session + aclose()` path.
- Updated `close_all_avatar_sessions`: handles both record types on shutdown.
- 6/6 new tests pass + 8 existing avatar_viewers tests pass; ruff clean.
