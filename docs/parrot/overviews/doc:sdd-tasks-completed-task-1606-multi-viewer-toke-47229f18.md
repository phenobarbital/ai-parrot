---
type: Wiki Overview
title: 'TASK-1606: Mode C — multi-viewer token endpoint'
id: doc:sdd-tasks-completed-task-1606-multi-viewer-token-endpoint-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Mode C: because we control the LiveKit room (LITE), multiple people can
  watch the'
---

# TASK-1606: Mode C — multi-viewer token endpoint

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1604
**Assigned-to**: unassigned

---

## Context

Mode C: because we control the LiveKit room (LITE), multiple people can watch the
same agent stream. `mint_room_tokens` already mints ONE subscribe-only viewer
token per call; we need to mint **N additional** viewer tokens (distinct
identities) for an existing live session's room. Q-mode-c-scope resolved: in
scope now. (Spec §2 Mode C, §4 M-C1, §7.)

---

## Scope

- Add an authenticated endpoint
  `POST /api/v1/avatar/{agent_id}/viewers` that, given an active LITE session's
  `session_id` (from `app['avatar_sessions']`), mints `count` subscribe-only
  tokens with distinct identities for that room via
  `LiveKitRoomManager.mint_room_tokens`, and returns the list
  `[{identity, livekit_url, client_token}]`.
- Validate: session exists (404 if not), `count` bounded (e.g. 1–50),
  opt-in gate consistent with LITE (`is_avatar_enabled`).
- Return **subscribe-only** tokens only — never agent/publish tokens or secrets.
- Tests (fakes for `mint_room_tokens`).

**NOT in scope**: FULL mode rooms (LiveAvatar-managed; viewer token comes from
its `/start`); changing token-mint internals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/avatar.py` | MODIFY | add `AvatarViewersView` + handler + route |
| `packages/ai-parrot-server/tests/handlers/test_avatar_viewers.py` | CREATE | mint N tokens, bounds, 404 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Signatures
```python
# liveavatar/room_manager.py
class LiveKitRoomManager:                      # :47
    def mint_room_tokens(self, room: str, identity: str, ...) -> LiveKitRoomTokens: ...  # :78
# liveavatar/models.py
class LiveKitRoomTokens(BaseModel):            # :58
    livekit_url: str  # :72
    room: str         # :73
    client_token: str # :74  (subscribe-only — safe to expose)
    agent_token: str  # :78  (NEVER expose)
# handlers/avatar.py
#   AVATAR_SESSIONS_KEY = "avatar_sessions"  (LITE session store: session_id -> {client, handle})
#   _start_avatar_session :77 ; AvatarSessionView :455 ; register_avatar_routes :519  (mirror its auth pattern)
#   @is_authenticated() + @user_session() on the view (see avatar_fullmode.py views for the exact decorator stack)
```

### Does NOT Exist
- ~~a viewers endpoint today~~ — this task creates it
- ~~`mint_browser_token`~~ — deleted in TASK-1601 (was publish-audio, Phase C); use `mint_room_tokens` (subscribe-only)

---

## Implementation Notes
- Derive the room name from the stored session handle (the LITE
  `AvatarSessionHandle`/room the session was started in).
- Use distinct identities (e.g. `viewer-{i}-{shortuuid}`) so LiveKit does not
  collapse them into one participant.
- Mirror `avatar_fullmode.py` for the authenticated `BaseView` decorator stack.

---

## Acceptance Criteria
- [ ] `POST /api/v1/avatar/{agent_id}/viewers {session_id, count}` returns `count` distinct subscribe-only tokens.
- [ ] 404 for unknown session; `count` out of bounds → 400.
- [ ] No agent/publish token or secret in the response.
- [ ] Two viewer tokens can each connect and subscribe to the same room (fake-verified).

---

## Agent Instructions
Standard SDD flow.

## Completion Note
Implemented 2026-06-19. Added `_mint_viewer_tokens` handler function and `AvatarViewersView`
BaseView class to avatar.py. Route registered at `POST /api/v1/avatar/{agent_id}/viewers`.
Validates: session_id required (400 if absent), session must exist (404 if not), count bounded
1-50 (400 otherwise). Mints `count` distinct viewer tokens using uuid4 identities. Returns only
client_token/identity/livekit_url — never agent_token. 8 tests in test_avatar_viewers.py all pass.
