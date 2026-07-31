---
type: Wiki Overview
title: 'TASK-1605: Mode D — mount VoiceChatHandler (/ws/voice) in the main server'
id: doc:sdd-tasks-completed-task-1605-mount-gemini-voice-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mode D (Gemini Live + LITE avatar tee, FEAT-245) is fully implemented in
relates_to:
- concept: mod:parrot.voice.handler
  rel: mentions
---

# TASK-1605: Mode D — mount VoiceChatHandler (/ws/voice) in the main server

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1604
**Assigned-to**: unassigned

---

## Context

Mode D (Gemini Live + LITE avatar tee, FEAT-245) is fully implemented in
`VoiceChatHandler` + `VoiceAvatarSession`, but `/ws/voice` is only registered by
the standalone `voice/server.py` (deleted) — it is **not mounted** in
`ai-parrot-server`. Q-mode-d-mount resolved: mount it in the main server.
(Spec §2 Mode D, §4 M-D1, §7.)

---

## Scope

- Add a `_register_voice_chat_routes` (or extend `setup()`) in `BotManager` that
  calls `VoiceChatHandler.setup_routes(app)` under the optional-integration guard
  (lazy import; missing `ai-parrot-integrations[voice]`/Gemini logs a warning and
  skips — mirror `_register_avatar_routes`).
- Confirm JWT auth path (`parrot/core/ws_auth.py`) works through the mounted
  route, and the `avatar:true` `start_session` path opens a `VoiceAvatarSession`.
- Add a handler test (fakes acceptable) + one real-sandbox marker test
  (`@pytest.mark.integration`, needs `LIVEAVATAR_API_KEY` + Gemini creds).

**NOT in scope**: changing `VoiceChatHandler`/`VoiceAvatarSession` internals;
multi-viewer (TASK-1606).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | register `/ws/voice` under guard |
| `packages/ai-parrot-server/tests/handlers/test_voice_chat_mount.py` | CREATE | route mounted + avatar:true path |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Signatures
```python
# packages/ai-parrot-integrations/src/parrot/voice/handler.py
class VoiceChatHandler:                       # :169
    def setup_routes(self, app, ...): ...     # :274  (registers GET /ws/voice)
    async def handle_websocket(self, request): ...  # :397
    # start_session with avatar:true → VoiceAvatarSession.start (~:761), "audio":"dual" (~:786)
    # _send_voice_response tees Gemini PCM → avatar_session.speak (~:1351-1366)
def create_voice_server(...): ...             # :1443  (keep; alternative bootstrap)

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py
class VoiceAvatarSession:                      # :55
    async def start(...): ...                  # :90  (24 kHz, no resample)
    async def speak(self, pcm: bytes): ...     # :223
    async def finish_turn(self): ... ; async def interrupt(self): ... ; async def aclose(self): ...
    @property
    def viewer_credentials(self): ...          # subscribe-only token

# manager.py pattern to mirror:
#   _register_avatar_routes :1486 (lazy import + guard + add_view + on_cleanup)
```

### Does NOT Exist
- ~~a per-agent `/ws/voice/{agent_id}` route~~ — `/ws/voice` is a single route; the bot is built per-connection from the `start_session` config
- ~~`VoiceChatHandler` already wired in `manager.py`~~ — it is NOT (this task wires it)

---

## Implementation Notes
- Gemini Live emits PCM at **24 kHz**; `AvatarWebSocket` expects 24 kHz →
  **no resampling** in this path (do not add any).
- Guard the import so a server without `[voice]`/Gemini still boots.
- Reuse `is_avatar_enabled` opt-in already inside the handler's avatar path.

---

## Acceptance Criteria
- [ ] `/ws/voice` is registered when the voice stack is installed; skipped with a warning otherwise.
- [ ] Fake-driven test: a `start_session{avatar:true}` returns viewer credentials + `"audio":"dual"`.
- [ ] Gemini→avatar tee path exercised (fake `VoiceAvatarSession`) without resampling.
- [ ] Server still boots when `[voice]` is absent.

---

## Agent Instructions
Standard SDD flow.

## Completion Note
Implemented 2026-06-19. Added `_register_voice_chat_routes(app)` to BotManager in manager.py.
Mirrors the `_register_avatar_routes` pattern: lazy import of `VoiceChatHandler` from
`parrot.voice.handler`; ImportError → warning + return False. Calls `handler.setup_routes(app,
include_health=False, include_static=False)`. Wired via `self._register_voice_chat_routes(self.app)`
in `setup()` after `_register_voice_routes`. 3 tests created in test_voice_chat_mount.py pass.
Total handler test count: 71.
