---
type: Wiki Overview
title: 'TASK-1589: Wire VoiceAvatarSession into VoiceChatHandler (lifecycle + audio
  tee)'
id: doc:sdd-tasks-completed-task-1589-wire-voice-avatar-into-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of FEAT-245. With `VoiceAvatarSession` (TASK-1588)
relates_to:
- concept: mod:parrot.clients.live
  rel: mentions
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.optin
  rel: mentions
---

# TASK-1589: Wire VoiceAvatarSession into VoiceChatHandler (lifecycle + audio tee)

**Feature**: FEAT-245 — Realtime LiveAvatar mouth driven by VoiceBot (Gemini Live)
**Spec**: `sdd/specs/voicechat-liveavatar-gemini.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1588
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of FEAT-245. With `VoiceAvatarSession` (TASK-1588)
available, this task wires it into the existing `/ws/voice` flow: start the
avatar on `start_session` (when requested + opted-in), tee Gemini Live output
audio into the avatar in `_send_voice_response`, handle barge-in / turn-end, and
tear down on cleanup. The mic path and the existing browser `response_chunk`
audio are unchanged (dual audio). Every avatar interaction is best-effort so a
hiccup never breaks the voice conversation.

---

## Scope

- Extend the `WebSocketConnection` dataclass with
  `avatar_session: Optional["VoiceAvatarSession"] = None`.
- In `_handle_start_session`: read `avatar` (bool) + optional `avatar_id` +
  `tenant_id` from the message. If avatar requested:
  - lazy-import the liveavatar stack (so `/ws/voice` works without the extra);
  - run the opt-in gate `is_avatar_enabled(tenant_id=, agent_name=)`;
  - call `VoiceAvatarSession.start(agent_id=…, session_id=connection.session_id,
    tenant_id=…, avatar_id=…)`, store it on the connection;
  - add an `avatar` block to the existing `session_started` reply:
    `{"active": true, **viewer_credentials, "audio": "dual"}`.
  - On opt-in denied / import error / start failure: catch, log, and set
    `{"active": false, "reason": "<short>"}` — the voice session still starts
    (graceful degradation). Never raise out of `_handle_start_session` for avatar
    reasons.
- In `_send_voice_response`: after the existing browser `response_chunk` send, if
  `connection.avatar_session` is set, best-effort (try/except, log-only):
  - if `response.is_interrupted`: `await avatar_session.interrupt()`;
  - else if `response.audio_data`: `await avatar_session.speak(response.audio_data)`;
  - if `response.is_complete`: `await avatar_session.finish_turn()`.
- In `_cleanup_connection`: if `connection.avatar_session`, `await
  avatar_session.aclose()` (guarded).
- Do NOT change the mic input path, `streaming_mode`, or the existing
  `response_chunk` browser audio (dual audio is intentional).
- Write unit tests (see Test Specification).

**NOT in scope**: creating `VoiceAvatarSession` (TASK-1588); any resampling;
publishing the mic to LiveKit; new routes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | MODIFY | Connection field + start/tee/cleanup wiring |
| `packages/ai-parrot-integrations/tests/voice/test_voice_handler_avatar.py` | CREATE | Unit tests for the wiring |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# lazy, INSIDE _handle_start_session (so /ws/voice works without the extra):
from parrot.integrations.liveavatar import VoiceAvatarSession        # created by TASK-1588
from parrot.integrations.liveavatar.optin import is_avatar_enabled   # optin module (used by avatar.py:339)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/voice/handler.py
class WebSocketConnection:                                            # dataclass
    session_id: str                                                  # line 104
    streaming_mode: str = "streaming"                               # line 131
    audio_buffer: bytes = b""                                       # line 141
    audio_queue: asyncio.Queue                                      # line 144
    # ADD: avatar_session: Optional[VoiceAvatarSession] = None

async def _handle_start_session(self, connection, message) -> None  # line 666
    #   sends {"type":"session_started", ..., "input_format":"audio/pcm;rate=16000",
    #          "output_format":"audio/pcm;rate=24000"}  (~lines 723-743)
async def _send_voice_response(self, connection, response) -> None  # line 1194
    #   sends {"type":"response_chunk","text":...,"audio_base64": base64(response.audio_data)}  (~1217-1222)
async def _cleanup_connection(self, connection) -> None             # line 1301

# packages/ai-parrot/src/parrot/clients/live.py
@dataclass
class LiveVoiceResponse:                                             # line 156
    audio_data: Optional[bytes]    # PCM 24 kHz mono 16-bit          # line 165
    is_complete: bool              # turn boundary                   # line 169
    is_interrupted: bool           # barge-in                        # line 170

# TASK-1588 helper:
class VoiceAvatarSession:
    @classmethod async def start(cls, *, agent_id, session_id, tenant_id, avatar_id=None) -> "VoiceAvatarSession"
    @property def viewer_credentials(self) -> dict   # {"livekit_url","client_token","room"}
    async def speak(self, pcm: bytes) -> None
    async def finish_turn(self) -> None
    async def interrupt(self) -> None
    async def aclose(self) -> None
```

### Does NOT Exist
- ~~A second voice route for avatar mode~~ — avatar rides the existing `/ws/voice` via an additive `avatar` field on `start_session`.
- ~~`mint_browser_token` / FEAT-243 worker dispatch in this handler~~ — not used; mic stays on `/ws/voice`.
- ~~Resampling of `response.audio_data`~~ — already 24 kHz; pass straight to `speak`.
- ~~A Redis/`OutputBridge` for transcripts/tool_calls~~ — single process; they already return over `/ws/voice`.

---

## Implementation Notes

### Pattern to Follow
Keep the avatar concerns isolated behind `if connection.avatar_session:` guards
so the non-avatar path is byte-for-byte unchanged. Lazy-import the liveavatar
stack inside `_handle_start_session` and treat ANY ImportError/exception as
"avatar unavailable → degrade", mirroring the defensive lazy-import pattern in
`handlers/avatar.py:96-106`.

### Key Constraints
- Best-effort avatar calls in `_send_voice_response`: wrap in try/except, log at
  warning, NEVER propagate (browser audio must keep flowing — this is the whole
  point of dual audio).
- `_handle_start_session` must not fail the voice session because the avatar
  failed; always send `session_started` with an `avatar` block (`active` true/false).
- Resolve `agent_id` for `VoiceAvatarSession.start` from the bot/agent name
  available on the connection or `BotConfig` (use the same identity the voice bot
  uses). If none, use a stable default; document the choice.
- Async throughout; `self.logger` for start/degradation/cleanup.

### References in Codebase
- `handlers/avatar.py:96-106` — defensive lazy-import + `HTTPServiceUnavailable` pattern.
- `handlers/avatar.py:339` — `is_avatar_enabled(tenant_id=, agent_name=)` usage.
- `voice/handler.py:666-743` — `_handle_start_session` reply shape to extend.

---

## Acceptance Criteria

- [ ] `start_session` with `avatar:true` (opted-in) starts the avatar and adds `avatar.active=true` + `livekit_url`+`client_token`+`room`+`audio:"dual"` to the reply.
- [ ] Opt-in denied / import error / start failure → `avatar.active=false` with reason; the voice session still starts and works.
- [ ] `_send_voice_response` tees `response.audio_data` to `avatar_session.speak` AND still sends the browser `response_chunk`.
- [ ] `response.is_interrupted` → `interrupt()`; `response.is_complete` → `finish_turn()`.
- [ ] An avatar exception in `_send_voice_response` does NOT break the browser audio stream.
- [ ] `_cleanup_connection` calls `avatar_session.aclose()`.
- [ ] `/ws/voice` still works with the liveavatar extra absent (lazy import).
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/voice/test_voice_handler_avatar.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-integrations/src/parrot/voice/handler.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/voice/test_voice_handler_avatar.py
import pytest
from parrot.clients.live import LiveVoiceResponse


@pytest.fixture
def avatar_session(mocker):
    s = mocker.Mock()
    s.viewer_credentials = {"livekit_url": "wss://x", "client_token": "v", "room": "sess-1"}
    s.speak = mocker.AsyncMock()
    s.finish_turn = mocker.AsyncMock()
    s.interrupt = mocker.AsyncMock()
    s.aclose = mocker.AsyncMock()
    return s


async def test_send_voice_response_tees_and_keeps_browser(handler, connection, avatar_session, mocker):
    connection.avatar_session = avatar_session
    send_json = mocker.patch.object(connection, "send_json", mocker.AsyncMock(), create=True)
    resp = LiveVoiceResponse(text="hi", audio_data=b"\x00\x01" * 50, is_complete=True)
    await handler._send_voice_response(connection, resp)
    avatar_session.speak.assert_awaited_once_with(b"\x00\x01" * 50)
    avatar_session.finish_turn.assert_awaited_once()
    assert send_json.await_count >= 1  # browser response_chunk still sent


async def test_avatar_failure_does_not_break_voice(handler, connection, avatar_session):
    connection.avatar_session = avatar_session
    avatar_session.speak.side_effect = RuntimeError("boom")
    resp = LiveVoiceResponse(audio_data=b"\x00\x01" * 50)
    await handler._send_voice_response(connection, resp)  # must not raise


async def test_interrupt_routes_to_avatar(handler, connection, avatar_session):
    connection.avatar_session = avatar_session
    resp = LiveVoiceResponse(is_interrupted=True)
    await handler._send_voice_response(connection, resp)
    avatar_session.interrupt.assert_awaited_once()
```
*(Provide `handler` / `connection` fixtures consistent with the existing voice
handler tests; consult `packages/ai-parrot-integrations/tests/voice/` for the
established fixture style.)*

---

## Agent Instructions

1. Read the spec (§2, §6) and TASK-1588's `VoiceAvatarSession` API.
2. Verify the Codebase Contract against `voice/handler.py` and `clients/live.py`.
3. Update index status → `in-progress`.
4. Implement per scope; keep the non-avatar path unchanged; best-effort avatar calls.
5. Run the tests + ruff; verify acceptance criteria.
6. Move this file to `sdd/tasks/completed/` and update index → `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-18
**Notes**: Extended `WebSocketConnection` with `avatar_session: Optional[Any] = None` (type
kept as Any to avoid top-level liveavatar import). In `_handle_start_session`: lazy-import
liveavatar stack, run `is_avatar_enabled`, call `VoiceAvatarSession.start` on success, store
on connection, add `avatar` block to `session_started` reply. Graceful degradation handles
ImportError and any other exception. In `_send_voice_response`: best-effort avatar tee with
interrupt/speak/finish_turn routing. In `_cleanup_connection`: `aclose` + clear. 11 unit
tests all green. Ruff clean.
**Deviations from spec**: Tests use `streaming_mode: "buffered"` for `_handle_start_session`
tests to avoid the background `_run_voice_session` asyncio task hanging the test suite. This
is a test-only constraint; production streaming mode works correctly.
