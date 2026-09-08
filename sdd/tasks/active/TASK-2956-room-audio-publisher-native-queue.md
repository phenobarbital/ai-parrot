# TASK-2956: RoomAudioPublisher — explicit publisher identity, real native queue flush, failure propagation

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Parallel**: true
**Parallelism notes**: Touches only `room_audio_publisher.py` and `test_room_audio_publisher.py`.

---

## Context

Spec §2: "The current `RoomAudioPublisher.flush()` does not clear the native queue and must be corrected" and "call native `AudioSource.clear_queue()`"; §6 Does-NOT-Exist: "`RoomAudioPublisher.flush()` is not a native queue purge in the verified baseline." Also the publisher today connects with `tokens.agent_token` (`room_audio_publisher.py:144`) — the same fixed `avatar-agent` identity the avatar uses — and swallows `capture_frame` failures (`:196-200`). Module 3.

## Scope

- `RoomAudioPublisher.start(...)`: keep the existing `tokens: LiveKitRoomTokens` positional path for legacy callers, and add keyword alternative `*, livekit_url: str | None = None, token: str | None = None, track_name: str = "agent-voice", queue_size_ms: int = 1000, on_failure: Callable[[str], Awaitable[None] | None] | None = None`. Exactly one of `tokens` or (`livekit_url`+`token`) is required. Broadcast callers pass the **direct** publisher token (TASK-2954) and `track_name="direct-voice"`.
- `flush()` → call `self.source.clear_queue()` (verified `livekit.rtc.AudioSource.clear_queue(self) -> None` on livekit 1.1.14) in addition to the existing drop-flag; keep idempotent/never-raise.
- New `async wait_for_playout(self, timeout_s: float | None = None) -> bool` → `await asyncio.wait_for(self.source.wait_for_playout(), timeout_s)`; returns `False` on timeout; used only at normal completion (spec: "never wait for stale audio during cancellation").
- Failure propagation: on `capture_frame` exception, log **and** invoke `on_failure("capture_failed")` once, then set `self.failed = True` so later `capture_pcm` are no-ops; register `room.on("disconnected")` to call `on_failure("room_disconnected")`.
- `aclose()`: `clear_queue()` → unpublish track (`room.local_participant.unpublish_track(track.sid)` if available) → `source.aclose()` if exists → `room.disconnect()`; each step guarded, idempotent.
- Expose `identity` (from token `sub` if decodable, else caller-supplied) and `track_sid`.
- Tests in `tests/integrations/liveavatar/test_room_audio_publisher.py` extending its `_FakeRtc`/`_FakeAudioSource` fakes (lines 21-140): add `clear_queue`/`wait_for_playout` counters.

**NOT in scope**: token minting, broadcast routing, avatar session.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_audio_publisher.py` | MODIFY | Explicit identity, real flush, playout, failure hooks |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_room_audio_publisher.py` | MODIFY | Extend fakes + new tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.room_audio_publisher import RoomAudioPublisher, _require_livekit_rtc  # :68, :47
from parrot.integrations.liveavatar.models import LiveKitRoomTokens  # :37
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_audio_publisher.py
_SAMPLE_RATE = 24_000; _NUM_CHANNELS = 1; _BYTES_PER_SAMPLE = 2          # :40-42
class RoomAudioPublisher:                                                  # :68
    def __init__(self, room, source, track, audio_frame_cls, *, sample_rate=_SAMPLE_RATE, num_channels=_NUM_CHANNELS)  # :81 ; sets _closed, _flushing, logger
    @classmethod async def start(cls, tokens: LiveKitRoomTokens, *, sample_rate=..., num_channels=...) -> "RoomAudioPublisher"  # :115
        # :142-151: rtc.Room(); await room.connect(tokens.livekit_url, tokens.agent_token); rtc.AudioSource(sample_rate, num_channels);
        #           rtc.LocalAudioTrack.create_audio_track("agent-voice", source); rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE);
        #           await room.local_participant.publish_track(track, publish_opts)
    async def capture_pcm(self, pcm: bytes) -> None    # :170 (no-op if _closed/_flushing; frame = audio_frame_cls(data=..., sample_rate=..., num_channels=..., samples_per_channel=...); try/except swallows)
    async def flush(self) -> None                       # :205 (flag only + asyncio.sleep(0)) — MUST also clear native queue now
    async def aclose(self) -> None                      # :221 (room.disconnect())

# livekit.rtc (installed 1.1.14, verified)
rtc.AudioSource(sample_rate: int, num_channels: int, queue_size_ms: int = 1000, loop=None)
rtc.AudioSource.clear_queue(self) -> None ; rtc.AudioSource.wait_for_playout(self) -> None (async)
```
- Fakes in tests: `_FakeAudioSource :32`, `_FakeAudioFrame :44`, `_FakeLocalParticipant :61`, `_FakeRoom :71`, `_FakeRtc :111`, fixture at `:21` (patches `_require_livekit_rtc`).

### Does NOT Exist
- ~~`RoomAudioPublisher.flush()` clearing native audio~~ — baseline only toggles a flag.
- ~~`RoomAudioPublisher.wait_for_playout`, `on_failure`, `identity`~~ — you add them.
- ~~`livekit-rtc` as a separate distribution~~ — not installed; `livekit` 1.1.14 provides `livekit.rtc`.

## Implementation Notes

- Verify `unpublish_track` signature on the installed SDK before using it: `python -c "from livekit import rtc; import inspect; print(inspect.signature(rtc.LocalParticipant.unpublish_track))"`; if it needs `track.sid`, read it from the `LocalTrackPublication` returned by `publish_track` (store it in `start`).
- Keep `capture_pcm` hot-path cheap; `on_failure` is awaited outside the try that captures.
- Never log tokens; `identity` decode via base64 of the JWT payload only (no verification), same as `test_room_manager.py:82`.

## Acceptance Criteria

- [ ] `flush()` calls `source.clear_queue()` exactly once per call and remains idempotent after `aclose()`.
- [ ] `wait_for_playout(timeout_s=0.01)` returns `False` when the fake never resolves; `True` when it does.
- [ ] `start(livekit_url=..., token=..., track_name="direct-voice")` connects with that token and creates a track named `direct-voice`; legacy `start(tokens)` still uses `agent_token` + `agent-voice` (existing test `test_start_connects_with_agent_token_and_publishes_track` stays green).
- [ ] Capture exception → `on_failure("capture_failed")` once, `failed is True`, later captures no-op.
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_room_audio_publisher.py -q` green; `ruff check` clean.

## Test Specification

```python
async def test_flush_clears_native_queue(fake_rtc, publisher): 
    await publisher.flush(); assert publisher.source.clear_queue_calls == 1

async def test_wait_for_playout_timeout_returns_false(publisher): ...
async def test_start_with_explicit_token_and_track_name(fake_rtc): ...
async def test_capture_failure_invokes_on_failure_once(fake_rtc): ...
async def test_aclose_clears_queue_then_disconnects(fake_rtc, publisher): ...
```

## Agent Instructions
1. Read spec §2 "Audio routing, failure and interruption". 2. Verify anchors + SDK signatures in-venv. 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
