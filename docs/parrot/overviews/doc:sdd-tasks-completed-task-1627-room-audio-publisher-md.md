---
type: Wiki Overview
title: 'TASK-1627: livekit dependency + RoomAudioPublisher (headless room audio)'
id: doc:sdd-tasks-completed-task-1627-room-audio-publisher-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation of FEAT-256 (spec §2, §3 Module 1 + Module 4). Today ai-parrot
  only
relates_to:
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.room_manager
  rel: mentions
---

# TASK-1627: livekit dependency + RoomAudioPublisher (headless room audio)

**Feature**: FEAT-256 — LiveKit Direct Audio (avatar-optional livekit voice)
**Spec**: `sdd/specs/livekit-direct-audio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of FEAT-256 (spec §2, §3 Module 1 + Module 4). Today ai-parrot only
uses `livekit.api` (token minting); it cannot publish audio into the room. This
task adds the `livekit` realtime SDK and a headless publisher that joins the room
with the publish-capable `agent_token` and streams Supertonic PCM as an audio track.
This is what makes livekit voice work with **zero** LiveAvatar dependency.

---

## Scope

- Add the `livekit` realtime SDK (`~=1.1`, 1.1.10) to the extra that already
  carries `livekit-api` in `packages/ai-parrot-integrations/pyproject.toml`.
- Implement `RoomAudioPublisher` (spec §2 New Public Interfaces):
  - `start(tokens, *, sample_rate=24000, num_channels=1)` → join the room via
    `rtc.Room().connect(tokens.livekit_url, tokens.agent_token)`, create
    `rtc.AudioSource` + `rtc.LocalAudioTrack.create_audio_track(...)`, and
    `local_participant.publish_track(...)`.
  - `capture_pcm(pcm: bytes)` → wrap into `rtc.AudioFrame` and `source.capture_frame`.
  - `flush()` → drop queued audio (barge-in / interrupt).
  - `aclose()` → idempotent; disconnect room; never raise.
- Unit tests with the livekit SDK mocked (no real network).

**NOT in scope**: wiring it into the speaker (TASK-1628) or the start handler
(TASK-1629); any avatar-ON path; STT / mic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_audio_publisher.py` | CREATE | `RoomAudioPublisher` |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | add `livekit~=1.1` to the livekit extra (next to `livekit-api>=1.0`) |
| `packages/ai-parrot-integrations/tests/.../test_room_audio_publisher.py` | CREATE | unit tests (livekit mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from livekit import rtc                      # NEW dep (livekit ~1.1.x realtime SDK)
# tokens come from the existing room manager:
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager  # mint_room_tokens
from parrot.integrations.liveavatar.models import LiveKitRoomTokens          # models.py:58
```

### Existing Signatures to Use
```python
# room_manager.py — mint_room_tokens(session_id: str, agent_id: str) -> LiveKitRoomTokens
# models.py:58 — LiveKitRoomTokens(livekit_url, room, client_token, agent_token)
#   agent_token = publish grants (server-side only) → use THIS to connect the publisher.

# livekit realtime publish API (verified via livekit/python-sdks, v1.1.x):
#   room = rtc.Room(); await room.connect(url, token)
#   src = rtc.AudioSource(sample_rate, num_channels)
#   track = rtc.LocalAudioTrack.create_audio_track("agent-voice", src)
#   await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
#   await src.capture_frame(rtc.AudioFrame(data=..., sample_rate=24000, num_channels=1, samples_per_channel=...))
```

### Does NOT Exist
- ~~any existing `rtc.Room`/`AudioSource`/`LocalAudioTrack` usage in ai-parrot~~ — this is the first; build it.
- ~~`livekit` realtime SDK already installed~~ — only `livekit-api` is; add it.

---

## Implementation Notes

### Key Constraints
- Async throughout; `aclose()` idempotent and never raises (cleanup path).
- Supertonic PCM is **24 kHz mono 16-bit** — create `AudioSource(24000, 1)`; no resampling.
- Keep the publisher long-lived (do NOT `async with` it for a single turn — mirror the
  keep-alive caveat at `handlers/avatar.py:157-176`).
- Verify `livekit~=1.1` resolves with the existing `livekit-api>=1.0` (same 1.x line).

### References in Codebase
- `liveavatar/room_manager.py` — token minting + LiveKit Cloud env.
- `liveavatar/avatar_ws.py` — PCM chunking constants (24 kHz mono 16-bit) for frame sizing.

---

## Acceptance Criteria

- [ ] `livekit~=1.1` added; `from livekit import rtc` resolves alongside `livekit-api`.
- [ ] `RoomAudioPublisher.start` connects with `agent_token` and publishes an audio track.
- [ ] `capture_pcm` forwards frames to `AudioSource.capture_frame`.
- [ ] `aclose` is idempotent and disconnects the room.
- [ ] Unit tests pass (`pytest packages/ai-parrot-integrations -k room_audio_publisher -v`).
- [ ] `ruff check` clean on the new file.

---

## Test Specification
```python
# test_room_audio_publisher.py — livekit rtc mocked
async def test_start_publishes_audio_track(fake_room_tokens, monkeypatch): ...
async def test_capture_pcm_forwards_frames(...): ...
async def test_aclose_idempotent(...): ...
```

---

## Completion Note

Implemented `RoomAudioPublisher` in `liveavatar/room_audio_publisher.py`.

- `start()` classmethod: creates `rtc.Room`, connects with `agent_token`,
  creates `AudioSource(24000, 1)` + `LocalAudioTrack`, calls `publish_track`.
- `capture_pcm()`: computes `samples_per_channel = len(pcm) // 2`, wraps in
  `rtc.AudioFrame`, calls `source.capture_frame`. Caches `AudioFrame` class on
  instance to avoid repeated lazy imports in the hot path.
- `flush()`: sets/clears `_flushing` flag to drop in-flight frames on barge-in.
- `aclose()`: idempotent; calls `room.disconnect()`; swallows all exceptions.
- `livekit~=1.1` added to the `liveavatar` extra in `pyproject.toml`.
- 8/8 unit tests pass; ruff clean.
