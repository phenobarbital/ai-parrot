---
type: Wiki Overview
title: 'TASK-1590: Integration tests for VoiceChat → LiveAvatar (Gemini Live)'
id: doc:sdd-tasks-completed-task-1590-voicechat-avatar-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of FEAT-245. The unit tests in TASK-1588/1589 cover
  the
relates_to:
- concept: mod:parrot.clients.live
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.voice_session
  rel: mentions
- concept: mod:parrot.voice.handler
  rel: mentions
---

# TASK-1590: Integration tests for VoiceChat → LiveAvatar (Gemini Live)

**Feature**: FEAT-245 — Realtime LiveAvatar mouth driven by VoiceBot (Gemini Live)
**Spec**: `sdd/specs/voicechat-liveavatar-gemini.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1588, TASK-1589
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of FEAT-245. The unit tests in TASK-1588/1589 cover the
helper and the handler wiring in isolation. This task adds the cross-module
end-to-end test that proves the dual path: a Gemini Live response (audio 24 kHz)
flows BOTH to the browser (`response_chunk`) AND to the avatar mouth
(`AvatarWebSocket.send_audio_frame`) — with no resampling — through the real
`VoiceAvatarSession` wired into `_send_voice_response`.

---

## Scope

- Add `test_gemini_audio_to_avatar_end_to_end`: build a real `VoiceAvatarSession`
  whose underlying `AvatarWebSocket` / `LiveAvatarClient` / `LiveKitRoomManager`
  are mocked (reuse the TASK-1588 fixture style), attach it to a
  `WebSocketConnection`, and drive `_send_voice_response` with a
  `LiveVoiceResponse(audio_data=<24k pcm>, is_complete=True)`. Assert BOTH the
  browser `response_chunk` was sent AND `AvatarWebSocket.send_audio_frame` was
  called with the same bytes (no transform), and `finish_speaking` on completion.
- Add `test_barge_in_clears_avatar`: a `LiveVoiceResponse(is_interrupted=True)`
  results in `AvatarWebSocket.interrupt()`.
- Place tests under `packages/ai-parrot-integrations/tests/voice/`. No real
  network / LiveKit / LiveAvatar / Gemini connections — fakes/mocks only.

**NOT in scope**: changing production code (a discovered gap is fixed in the
relevant module's task, not here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py` | CREATE | Cross-module end-to-end tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession  # TASK-1588
from parrot.clients.live import LiveVoiceResponse                            # clients/live.py:156
from parrot.voice.handler import VoiceChatHandler                            # voice/handler.py
```

### Existing Signatures to Use
```python
# LiveVoiceResponse(audio_data: bytes|None, is_complete: bool, is_interrupted: bool)  # live.py:165,169,170
# VoiceChatHandler._send_voice_response(self, connection, response)                   # handler.py:1194
# VoiceAvatarSession.speak/finish_turn/interrupt → AvatarWebSocket.send_audio_frame/finish_speaking/interrupt
#   AvatarWebSocket.send_audio_frame does NO resampling (avatar_ws.py:136,146)
```

### Does NOT Exist
- ~~Real Redis / LiveKit / Gemini deps in tests~~ — mock `AvatarWebSocket`, client, room manager (TASK-1588 fixture).
- ~~A resampling assertion~~ — assert bytes pass through unchanged (24 kHz match).

---

## Implementation Notes

### Pattern to Follow
Reuse the `patched_stack` fixture style from
`test_voice_avatar_session.py` (TASK-1588) to build a real `VoiceAvatarSession`
over mocked transport, then exercise it through the handler's
`_send_voice_response` (TASK-1589). Keep assertions on the mocked
`AvatarWebSocket` methods.

### Key Constraints
- Deterministic, fast, no sleeps.
- Same PCM bytes object asserted on both the browser send and the avatar send
  (proves no transform).

### References in Codebase
- `tests/voice/test_voice_avatar_session.py` (TASK-1588) — fixture style.
- `tests/voice/test_voice_handler_avatar.py` (TASK-1589) — handler fixtures.

---

## Acceptance Criteria

- [ ] `test_gemini_audio_to_avatar_end_to_end` proves dual delivery (browser `response_chunk` + avatar `send_audio_frame`) with identical bytes.
- [ ] `finish_speaking` is called on `is_complete`.
- [ ] `test_barge_in_clears_avatar` proves `interrupt()` on `is_interrupted`.
- [ ] Tests use only fakes/mocks (no real network).
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py -v`
- [ ] Full voice suite green: `pytest packages/ai-parrot-integrations/tests/voice/ -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py
import pytest
from parrot.clients.live import LiveVoiceResponse
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession


async def test_gemini_audio_to_avatar_end_to_end(patched_stack, handler, connection, mocker):
    # patched_stack (from TASK-1588) mocks AvatarWebSocket/client/room manager
    _, _, ws, _ = patched_stack
    connection.avatar_session = await VoiceAvatarSession.start(
        agent_id="ag", session_id="sess-1", tenant_id=None
    )
    mocker.patch.object(connection, "send_json", mocker.AsyncMock(), create=True)
    pcm = b"\x00\x01" * 4800
    await handler._send_voice_response(connection, LiveVoiceResponse(audio_data=pcm, is_complete=True))
    ws.send_audio_frame.assert_awaited_once_with(pcm)   # no resample/transform
    ws.finish_speaking.assert_awaited_once()


async def test_barge_in_clears_avatar(patched_stack, handler, connection):
    _, _, ws, _ = patched_stack
    connection.avatar_session = await VoiceAvatarSession.start(
        agent_id="ag", session_id="sess-1", tenant_id=None
    )
    await handler._send_voice_response(connection, LiveVoiceResponse(is_interrupted=True))
    ws.interrupt.assert_awaited_once()
```

---

## Agent Instructions

1. Read the spec (§4) and TASK-1588/1589.
2. Confirm TASK-1588 and TASK-1589 are in `sdd/tasks/completed/` before starting.
3. Update index status → `in-progress`.
4. Implement the integration tests per scope.
5. Run the targeted + full voice test suite.
6. Move this file to `sdd/tasks/completed/` and update index → `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-18
**Notes**: Created `test_voicechat_avatar_integration.py` with 4 cross-module tests
using a real `VoiceAvatarSession` over mocked transport (reuses patched_stack fixture
style from TASK-1588). Tests cover: dual delivery end-to-end (browser + avatar receive
same PCM), mid-turn audio without finish_speaking, barge-in clears avatar without
speaking, and byte-identity assertion proving zero-copy (no resampling). Full voice
suite: 94 passed, 1 skipped (pre-existing skip).
**Deviations from spec**: Added two extra tests beyond the spec's two required tests
(mid-turn no-finish and byte-identity) for stronger coverage. No production code changes.
