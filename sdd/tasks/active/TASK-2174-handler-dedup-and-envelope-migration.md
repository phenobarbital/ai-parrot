# TASK-2174: VoiceChatHandler: delete duplicated _run_turn, migrate envelope + chat.html + docs

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2171, TASK-2173
**Assigned-to**: unassigned
**Parallel-safe**: no — Integrations layer — depends on both the session hook and the VoiceBot migration.

---

## Context

`_HandlerVoiceSession` (`handler.py:264`) exists for one reason: it needs a
richer WebSocket frame protocol than `VoiceSession._relay()` provides. To get
it, it overrides `_relay()` — and then also re-implements `_run_turn()`
(`handler.py:305-360`), duplicating the reconnection loop so the turn can be
driven through `bot.ask_stream()` instead of the raw client. Its own docstring
documents the duplication as deliberate. With `build_frames()` (TASK-2171) the
override is no longer necessary.

This task also lands the consumer half of the envelope break: two handler call
sites (`:1481-1484`, `:1614-1617`), the legacy branch in the shipped
`chat.html:1096-1097`, and the frontend guide.

Implements: **Spec §3 Module 8**.

---

## Scope

- Delete `_HandlerVoiceSession._run_turn()` (`handler.py:305-360`) and express
  the handler's richer protocol as a `build_frames()` override.
- Preserve the handler's existing behaviors that the base class lacks:
  `go_away` handling (`handler.py:298`), the thought-filter regex, STT-only
  frame suppression, and the LiveAvatar audio tee.
- Migrate both `user_transcription` reads (`:1481-1484`, `:1614-1617`) to
  canonical `role`.
- Remove the legacy `message.user_transcription` branch in
  `voice/ui/chat.html:1096-1097` (the main `transcription`/`is_user` path stays).
- Update `docs/frontend/voicebot-realtime-frontend-guide.md` (`:137`) to document
  the canonical envelope.
- Tests per spec §4.

**NOT in scope**: the `ai-parrot-server` and integrations *test* fixtures —
TASK-2175.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | MODIFY | Delete `_run_turn`, `build_frames` override, envelope migration |
| `packages/ai-parrot-integrations/src/parrot/voice/ui/chat.html` | MODIFY | Remove legacy branch at `:1096-1097` |
| `docs/frontend/voicebot-realtime-frontend-guide.md` | MODIFY | Document the canonical envelope |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.voice.session import VoiceSession          # core; handler.py:50 (lazy-import guarded)
from parrot.voice.handler import VoiceChatHandler      # handler.py:388
from parrot.models.voice import VoiceConfig, VoiceProvider
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/voice/handler.py
from parrot.voice.session import VoiceSession                  # line 50 (inside try/except)
VoiceSession = Any                                             # line 54 (fallback)

def resolve_voice_client_class(provider) -> type:              # line 79
    if provider == _VoiceProvider.NOVA:                        # line 106
        from parrot.clients.nova import NovaClient; return NovaClient
    from parrot.clients.live import GeminiLiveClient; return GeminiLiveClient   # line 111

class _HandlerVoiceSession(VoiceSession):                      # line 264
    # go_away → session_warning + reconnect_required           # lines 285-303
    async def _run_turn(self, turn_no: int) -> None:           # line 305 ← DELETE
        stream = bot.ask_stream(                               # line 328
            audio_input=self._audio_iterator(queue),
            session_id=self.session_id,
            user_id=self._connection.user_id,
            stt_only=self._connection.stt_only,
        )

class VoiceChatHandler:                                        # line 388
    def resolve_provider_client(provider): ...                 # line 490
    if metadata.get("user_transcription"):                     # line 1481 ← MIGRATE
        {"type": "transcription", "text": ..., "is_user": True}    # lines 1482-1486
    async def _run_voice_session(self, connection) -> None:    # line 1527
        if bot._llm is None:                                   # line 1550
            config = bot._resolve_llm_config()
            bot._llm = bot._create_llm_client(config, bot.conversation_memory)
        connection.voice_session = _HandlerVoiceSession(...)   # line 1557
    async def _send_voice_response(self, connection, response): # line ~1576
        if response.metadata.get("user_transcription"):        # line 1614 ← MIGRATE
```

### Does NOT Exist

- ~~`VoiceBotHandler`~~ — the class is `VoiceChatHandler` (`handler.py:388`). No class by that name exists.
- ~~A voice handler in `ai-parrot-server` source~~ — the server only *mounts* this handler (`parrot/manager/manager.py:1528-1550`). Do not look for a second handler to migrate.
- ~~`metadata["user_transcription"]` after TASK-2167~~ — no longer produced. Reading it yields nothing.
- ~~An `__init__.py` to add on the core `parrot/voice/` side~~ — this package is split across two distributions via `pkgutil.extend_path` (`parrot/voice/__init__.py` in integrations). Adding a core one breaks `parrot.voice.session`.

---

## Implementation Notes

### Key Constraints
- The handler's frame protocol is richer than the base class's on purpose —
  `build_frames()` must reproduce it exactly. Diff the emitted frames before and
  after; the frontend contract beyond the envelope change must not shift.
- Keep the `go_away` → `session_warning` behavior (`handler.py:285-303`). Gemini
  now also sets `reconnect_required` (TASK-2168), so verify the two paths do not
  double-count a reconnect.
- STT-only suppression lives in `_send_voice_response()` and must keep working
  from canonical `role` rather than the removed metadata key.
- `chat.html`: remove only the legacy `message.user_transcription` branch
  (`:1096-1097`). The main `transcription`/`is_user` path above it stays.

---

## Acceptance Criteria

- [ ] `_HandlerVoiceSession` no longer defines `_run_turn()`
- [ ] Exactly one reconnection loop remains in the codebase (`voice/session.py`)
- [ ] The handler's frame output is unchanged apart from the intended envelope migration
- [ ] `go_away` → `session_warning` still works and does not double-count reconnects
- [ ] STT-only frame suppression still works, driven by `role`
- [ ] No `user_transcription` reference remains in `handler.py` or `chat.html`
- [ ] Frontend guide documents the canonical envelope
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/voice/ -v`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# extend packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py

class TestDeduplication:
    def test_run_turn_not_overridden(self):
        """The duplicated loop (handler.py:305-360) must be gone."""
        from parrot.voice.handler import _HandlerVoiceSession
        assert "_run_turn" not in _HandlerVoiceSession.__dict__

    def test_build_frames_overridden(self):
        from parrot.voice.handler import _HandlerVoiceSession
        assert "build_frames" in _HandlerVoiceSession.__dict__


class TestEnvelopeMigration:
    async def test_transcription_frame_from_role(self, handler, connection):
        """Replaces test_user_transcription_still_forwarded."""
        resp = LiveVoiceResponse(text="what's the weather", role="user")
        await handler._send_voice_response(connection, resp)
        assert sent_frame == {"type": "transcription",
                              "text": "what's the weather", "is_user": True}

    async def test_stt_only_suppresses_assistant(self, handler, connection):
        connection.stt_only = True
        await handler._send_voice_response(
            connection, LiveVoiceResponse(text="hi", role="assistant"))
        assert not sent_frames
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/googlelive-nova2-audiobot-homologation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
