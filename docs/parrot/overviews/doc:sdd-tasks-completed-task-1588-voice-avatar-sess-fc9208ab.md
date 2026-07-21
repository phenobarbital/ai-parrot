---
type: Wiki Overview
title: 'TASK-1588: VoiceAvatarSession helper (drive avatar mouth from a realtime PCM
  stream)'
id: doc:sdd-tasks-completed-task-1588-voice-avatar-session-helper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of FEAT-245. Today the only way to drive the LiveAvatar
relates_to:
- concept: mod:parrot.integrations.liveavatar.avatar_ws
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.client
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.room_manager
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.voice_session
  rel: mentions
---

# TASK-1588: VoiceAvatarSession helper (drive avatar mouth from a realtime PCM stream)

**Feature**: FEAT-245 — Realtime LiveAvatar mouth driven by VoiceBot (Gemini Live)
**Spec**: `sdd/specs/voicechat-liveavatar-gemini.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of FEAT-245. Today the only way to drive the LiveAvatar
"mouth" is FEAT-242's `AvatarTurnSpeaker`, which expects a **text → PCM**
synthesizer (Supertonic). Gemini Live already produces audio (PCM 24 kHz), so we
need a thinner abstraction that drives the avatar from a **raw realtime PCM
stream** — no TTS, no resampling. This task creates `VoiceAvatarSession`, which
encapsulates the avatar session lifecycle (LiveKit tokens + `LiveAvatarClient` +
`AvatarWebSocket`) and exposes a small `speak`/`finish_turn`/`interrupt`/`aclose`
API plus viewer credentials. TASK-1589 wires it into `VoiceChatHandler`.

---

## Scope

- Create `parrot/integrations/liveavatar/voice_session.py` with class
  `VoiceAvatarSession`:
  - `async classmethod start(*, agent_id, session_id, tenant_id, avatar_id=None) -> VoiceAvatarSession`:
    build `LiveAvatarConfig` from env (`LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID`
    or the `avatar_id` override, `LIVEAVATAR_BASE_URL`, `LIVEAVATAR_SANDBOX`);
    `LiveKitRoomManager().mint_room_tokens(session_id, agent_id)` (via
    `asyncio.to_thread`); build `livekit_config` (`livekit_url`, `livekit_room`,
    `livekit_client_token=agent_token`); `LiveAvatarClient(cfg)` → `aopen()` →
    `create_session_token(cfg, livekit_config=...)` (set `handle.session_id` /
    `handle.tenant_id`) → `start_session(handle)`; open `AvatarWebSocket(handle)`
    (enter the context / connect) and `await ws.start_speaking()`. On any failure,
    close partially-opened resources and re-raise.
  - `viewer_credentials` property → `{"livekit_url", "client_token", "room"}`
    (the subscribe-only `client_token` + room name; NEVER the agent_token /
    session_token / ws_url).
  - `async speak(pcm: bytes) -> None` → `await self._ws.send_audio_frame(pcm)`
    (NO resampling — input is already 24 kHz mono 16-bit).
  - `async finish_turn() -> None` → `await self._ws.finish_speaking()`.
  - `async interrupt() -> None` → `await self._ws.interrupt()`.
  - `async aclose() -> None` → close `AvatarWebSocket`, then
    `client.stop_session(handle)` + `client.aclose()`. Idempotent + never raises.
- Export `VoiceAvatarSession` from `parrot/integrations/liveavatar/__init__.py`
  (add to imports + `__all__`).
- Keep the opt-in gate OUT of this helper — the caller (TASK-1589) runs
  `is_avatar_enabled` before calling `start` (so the helper stays transport-only
  and unit-testable without the optin module). Document this in the docstring.
- Write unit tests (see Test Specification).

**NOT in scope**: any change to `VoiceChatHandler` (TASK-1589), to
`AvatarWebSocket` / `LiveAvatarClient` / `LiveKitRoomManager`, or resampling.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py` | CREATE | `VoiceAvatarSession` helper |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` | MODIFY | Export `VoiceAvatarSession` |
| `packages/ai-parrot-integrations/tests/voice/test_voice_avatar_session.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
from parrot.integrations.liveavatar.avatar_ws import AvatarWebSocket   # avatar_ws.py:60
from parrot.integrations.liveavatar.client import LiveAvatarClient     # client.py:57
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager  # room_manager.py:66
from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle, LiveAvatarConfig, LiveKitRoomTokens,          # re-exported via __init__
)
```

### Existing Signatures to Use
```python
# avatar_ws.py
class AvatarWebSocket:
    def __init__(self, handle: AvatarSessionHandle, *, session: aiohttp.ClientSession | None = None)  # line 83
    async def __aenter__(self) -> "AvatarWebSocket"                  # line 102 (connects + starts reader)
    async def __aexit__(self, ...) -> None                          # line 108 (closes + owns session)
    async def start_speaking(self) -> None                          # line 121 (awaits connected gate; RuntimeError on 30s timeout)
    async def send_audio_frame(self, pcm: bytes) -> None            # line 136 (base64 agent.speak; NO resample)
    async def finish_speaking(self) -> None                         # line 175
    async def interrupt(self) -> None                               # line 189

# client.py
class LiveAvatarClient:
    def __init__(self, cfg: LiveAvatarConfig, ...)                  # line 57
    async def aopen(self) -> "LiveAvatarClient"                     # line 85
    async def create_session_token(self, cfg, *, livekit_config: dict | None = None) -> AvatarSessionHandle  # line 116
    async def start_session(self, handle: AvatarSessionHandle) -> dict   # line 187
    async def stop_session(self, handle: AvatarSessionHandle) -> None    # line 216 (idempotent)
    async def aclose(self) -> None                                  # line 101

# room_manager.py
class LiveKitRoomManager:                                           # line 66 (reads LIVEKIT_* from env; KeyError if missing)
    def mint_room_tokens(self, room: str, identity: str) -> LiveKitRoomTokens  # line 78
    #   tokens.livekit_url, tokens.room, tokens.client_token (viewer), tokens.agent_token (avatar publisher)

# Lifecycle pattern reference (DO NOT async-with the client — it would stop the
# session on block exit before the browser joins): see avatar.py:157-176 comment.
```

### Does NOT Exist
- ~~`VoiceAvatarSession`~~ — this task creates it.
- ~~Any resampler in this path~~ — Gemini output is 24 kHz; `send_audio_frame` does no resampling (`avatar_ws.py:18,146`). Do NOT import `_resample_pcm_int16` / `AvatarVoiceProvider`.
- ~~`LiveKitRoomManager.mint_browser_token` / `.dispatch_worker`~~ — FEAT-243 worker path; NOT used. Use `mint_room_tokens`.
- ~~`AvatarTurnSpeaker`~~ — text→TTS speaker; not used here (we feed raw PCM).
- ~~A per-turn "begin" frame~~ — LITE mode has none; `start_speaking` only awaits the connected gate (`avatar_ws.py:121-134`).

---

## Implementation Notes

### Pattern to Follow
Mirror the session bring-up in `AvatarSessionOrchestrator.run` / `avatar.py`
`_start_avatar_session` (mint tokens → `create_session_token(livekit_config=)` →
`start_session`), but instead of synthesizing text, expose `speak(pcm)` that
forwards bytes straight to `AvatarWebSocket.send_audio_frame`. Manage the
`AvatarWebSocket` as a stored instance (enter on `start`, close on `aclose`) —
NOT a short-lived `async with` (the session must outlive a single block).

### Key Constraints
- `start` must clean up partial state on failure (close ws, stop+close client).
- `aclose` idempotent and never raises (teardown path).
- JWT minting via `asyncio.to_thread` (sync CPU work off the loop).
- `viewer_credentials` exposes ONLY `client_token` (+ url + room) — never the
  agent_token / session_token / ws_url.
- Async throughout; `self.logger`.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/avatar.py:143-195` — token mint + session start pattern (keep-alive caveat at 157-176).
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/orchestrator.py` — Phase A orchestration reference.

---

## Acceptance Criteria

- [ ] `VoiceAvatarSession.start` mints room tokens, starts a LITE session with `livekit_config`, opens `AvatarWebSocket`, awaits the connected gate.
- [ ] `viewer_credentials` returns `{livekit_url, client_token, room}` (no secrets leaked).
- [ ] `speak(pcm)` forwards bytes unchanged to `send_audio_frame` (no resample/transform).
- [ ] `finish_turn` / `interrupt` delegate to the matching `AvatarWebSocket` methods.
- [ ] `aclose` stops the session + closes the ws; safe to call twice; never raises.
- [ ] `start` cleans up partial resources on failure.
- [ ] Exported from the package `__init__`.
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/voice/test_voice_avatar_session.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/voice/test_voice_avatar_session.py
import pytest
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession


@pytest.fixture
def patched_stack(mocker):
    rm = mocker.Mock()
    tokens = mocker.Mock(livekit_url="wss://x", room="sess-1",
                         client_token="viewer-jwt", agent_token="agent-jwt")
    rm.mint_room_tokens.return_value = tokens
    mocker.patch("parrot.integrations.liveavatar.voice_session.LiveKitRoomManager", return_value=rm)

    client = mocker.Mock()
    client.aopen = mocker.AsyncMock(return_value=client)
    handle = mocker.Mock()
    client.create_session_token = mocker.AsyncMock(return_value=handle)
    client.start_session = mocker.AsyncMock()
    client.stop_session = mocker.AsyncMock()
    client.aclose = mocker.AsyncMock()
    mocker.patch("parrot.integrations.liveavatar.voice_session.LiveAvatarClient", return_value=client)

    ws = mocker.Mock()
    ws.__aenter__ = mocker.AsyncMock(return_value=ws)
    ws.start_speaking = mocker.AsyncMock()
    ws.send_audio_frame = mocker.AsyncMock()
    ws.finish_speaking = mocker.AsyncMock()
    ws.interrupt = mocker.AsyncMock()
    mocker.patch("parrot.integrations.liveavatar.voice_session.AvatarWebSocket", return_value=ws)
    mocker.patch.dict("os.environ", {"LIVEAVATAR_API_KEY": "k", "LIVEAVATAR_AVATAR_ID": "a"})
    return rm, client, ws, tokens


async def test_start_and_viewer_credentials(patched_stack):
    rm, client, ws, tokens = patched_stack
    s = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    assert s.viewer_credentials == {"livekit_url": "wss://x", "client_token": "viewer-jwt", "room": "sess-1"}
    client.start_session.assert_awaited_once()
    ws.start_speaking.assert_awaited_once()


async def test_speak_no_transform(patched_stack):
    _, _, ws, _ = patched_stack
    s = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    await s.speak(b"\x00\x01" * 100)
    ws.send_audio_frame.assert_awaited_once_with(b"\x00\x01" * 100)


async def test_aclose_idempotent(patched_stack):
    _, client, _, _ = patched_stack
    s = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-1", tenant_id=None)
    await s.aclose()
    await s.aclose()  # must not raise
    client.stop_session.assert_awaited()
```

---

## Agent Instructions

1. Read the spec (§2, §6) for full context.
2. Verify the Codebase Contract against `avatar_ws.py`, `client.py`, `room_manager.py`.
3. Update index status → `in-progress`.
4. Implement per scope; store the `AvatarWebSocket` (do not short-lived `async with`).
5. Run the tests + ruff; verify acceptance criteria.
6. Move this file to `sdd/tasks/completed/` and update index → `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-18
**Notes**: Created `voice_session.py` with `VoiceAvatarSession` class implementing
the full lifecycle: env-based `LiveAvatarConfig` build, async token minting via
`asyncio.to_thread`, `LiveAvatarClient` open/create/start, `AvatarWebSocket` enter
and `start_speaking` gate. `viewer_credentials` exposes only client_token+url+room.
`speak`/`finish_turn`/`interrupt` delegate directly with no resampling. `aclose` is
idempotent via a `_closed` flag. 9 unit tests all green. Exported from `__init__.py`.
**Deviations from spec**: Test for cleanup-on-failure was split into two tests
(start_session failure vs ws.start_speaking failure) to correctly reflect the actual
lifecycle order (ws is opened AFTER start_session, not before).
