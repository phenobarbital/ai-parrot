---
type: Wiki Overview
title: 'TASK-1628: Mode-aware AvatarTurnSpeaker sink'
id: doc:sdd-tasks-completed-task-1628-mode-aware-speaker-sink-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 2. The per-turn speaker (`AvatarTurnSpeaker`) currently pushes
---

# TASK-1628: Mode-aware AvatarTurnSpeaker sink

**Feature**: FEAT-256 — LiveKit Direct Audio (avatar-optional livekit voice)
**Spec**: `sdd/specs/livekit-direct-audio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1627
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The per-turn speaker (`AvatarTurnSpeaker`) currently pushes
Supertonic PCM only to the LiveAvatar `agent.speak` WebSocket. For the avatar-OFF
mode it must instead push PCM to the `RoomAudioPublisher` (TASK-1627). This task
makes the speaker's synth→send sink **mode-aware** while keeping its non-blocking
queue and graceful-degradation behavior.

---

## Scope

- Generalize `AvatarTurnSpeaker` so its background consumer sends synthesized PCM
  to an injected **sink**: the existing LiveAvatar WS (avatar-ON) OR
  `RoomAudioPublisher.capture_pcm` (avatar-OFF).
- Keep `.feed(text)` non-blocking and `.finish()` flush semantics unchanged.
- Map barge-in/interrupt to the active sink's flush.
- Unit tests for both routings.

**NOT in scope**: deciding which mode (TASK-1629); the publisher internals (TASK-1627).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/speaker.py` | MODIFY | inject a sink; route PCM by mode |
| `packages/ai-parrot-integrations/tests/.../test_speaker_sink.py` | CREATE | unit tests for both sinks |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# liveavatar/speaker.py
class AvatarTurnSpeaker:                       # async context manager (FEAT-242)
    def __init__(self, handle, synth_pcm_fn): ...
    def feed(self, text: str) -> None: ...     # non-blocking
    async def finish(self) -> None: ...
# Today the consumer sends PCM to the LiveAvatar WS (avatar_ws.AvatarWebSocket,
#   {"type":"agent.speak","audio": b64}).

# From TASK-1627:
class RoomAudioPublisher:
    async def capture_pcm(self, pcm: bytes) -> None: ...
    async def flush(self) -> None: ...
```

### Does NOT Exist
- ~~a sink abstraction in `AvatarTurnSpeaker` today~~ — it is hard-wired to the LiveAvatar WS; introduce the seam.

---

## Implementation Notes

### Key Constraints
- Do NOT block the text stream (keep the asyncio.Queue consumer pattern).
- Exactly one sink active per session (avatar-ON XOR avatar-OFF) — no double audio.
- Graceful degradation: a sink error logs + skips the turn audio (text still streams).

### References in Codebase
- `liveavatar/speaker.py` (current synth→send queue), `liveavatar/avatar_ws.py` (current sink).

---

## Acceptance Criteria

- [ ] With the avatar-OFF sink, PCM goes to `RoomAudioPublisher.capture_pcm` and NOT the LiveAvatar WS.
- [ ] With the avatar-ON sink, the existing LiveAvatar path is used unchanged.
- [ ] Interrupt flushes the active sink.
- [ ] Unit tests pass (`pytest packages/ai-parrot-integrations -k speaker_sink -v`).
- [ ] `ruff check` clean.

---

## Test Specification
```python
async def test_routes_to_room_when_avatar_off(...): ...
async def test_routes_to_liveavatar_when_avatar_on(...): ...
```

---

## Completion Note

Extended `AvatarTurnSpeaker` in `speaker.py` with a `room_publisher` parameter.

- `__init__`: added `room_publisher: Optional[RoomAudioPublisher] = None` (TYPE_CHECKING import to avoid circular deps).
- `__aenter__`: skips `AvatarWebSocket` creation when `room_publisher` is set.
- `_speak`: routes PCM to `publisher.capture_pcm()` (avatar-OFF) or `ws.send_audio_frame()` (avatar-ON). Exactly one path is taken.
- `finish`: calls `publisher.flush()` (avatar-OFF) or `ws.finish_speaking()` (avatar-ON).
- `interrupt()`: new method; cancels consumer + calls `publisher.flush()` or `ws.interrupt()` on the active sink.
- Existing avatar-ON tests (8/8) and new sink tests (6/6) all pass; ruff clean.
