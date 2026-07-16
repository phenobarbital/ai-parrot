---
type: Wiki Overview
title: 'TASK-1630: Direct-audio integration tests'
id: doc:sdd-tasks-completed-task-1630-direct-audio-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §4 Integration Tests. End-to-end (mocked room) coverage that the direct-audio
---

# TASK-1630: Direct-audio integration tests

**Feature**: FEAT-256 — LiveKit Direct Audio (avatar-optional livekit voice)
**Spec**: `sdd/specs/livekit-direct-audio.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1629
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests. End-to-end (mocked room) coverage that the direct-audio
mode and the auto-fallback work across the full start → turn → stop path.

---

## Scope

- `test_livekit_direct_audio_end_to_end_mock`: `/start` (avatar off) → one turn →
  assert PCM frames are captured to the room track → `/stop` tears down.
- `test_autofallback_end_to_end_mock`: `/start` (avatar on) where LiveAvatar start
  raises the no-credits `ClientResponseError` → assert fallback to the publisher →
  turn audio still flows; `/stop` clean.
- Shared fixtures: `fake_room_tokens`, mocked `rtc.Room`/`AudioSource`/`LocalAudioTrack`.

**NOT in scope**: new production code (covered by 1627–1629); the frontend.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/.../test_livekit_direct_audio_integration.py` | CREATE | integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# Use the components from TASK-1627/1628/1629:
#   RoomAudioPublisher, mode-aware AvatarTurnSpeaker, _start_avatar_session/_stop_avatar_session
# mint_room_tokens(session_id, agent_id) -> LiveKitRoomTokens
# avatar_upstream_error_response(exc) -> 402 (no credits) | 502
```

### Does NOT Exist
- ~~a live LiveKit/LiveAvatar in tests~~ — everything network-facing is mocked.

---

## Implementation Notes

### Key Constraints
- No real network: mock `rtc.Room.connect`, `AudioSource.capture_frame`, the
  LiveAvatar client `start_session` (to raise the 402 in the fallback test).
- Assert on frames captured to the room source (avatar-off) and clean teardown.

### References in Codebase
- The unit tests from TASK-1627–1629 for fixture/mocking patterns.

---

## Acceptance Criteria

- [ ] Both integration tests pass (`pytest packages/ai-parrot-server -k livekit_direct_audio_integration -v`).
- [ ] Auto-fallback test proves a `402` yields a working session (not an error).
- [ ] `/stop` leaves no orphaned room participant in the mocks.

---

## Test Specification
```python
async def test_livekit_direct_audio_end_to_end_mock(...): ...
async def test_autofallback_end_to_end_mock(...): ...
```

---

## Completion Note

Created `packages/ai-parrot-server/tests/handlers/test_livekit_direct_audio_integration.py` with 2 integration tests.

- `test_livekit_direct_audio_end_to_end_mock`: /start (avatar=false) → verifies publisher started (not LiveAvatar), room connected with `agent_token`, PCM captured (frame.data + samples_per_channel + sample_rate verified), /stop disconnects room + removes session from store.
- `test_autofallback_end_to_end_mock`: /start (avatar=true) with LiveAvatar 402 → verifies 200 response (not 402), LiveAvatar client closed, publisher started, turn audio flows, /stop cleans up.

Both tests use `_FakeRoomAudioPublisher` (inlined fake, same interface as the real class) injected via `sys.modules` — consistent with the project's test pattern for the lazy-import handler code. 2/2 tests pass; ruff clean.
