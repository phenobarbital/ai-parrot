# TASK-2956: RoomAudioPublisher — explicit publisher identity, real native queue flush, failure propagation

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: done
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

**Completed by**: `sdd-worker` (autonomous session)
**Date**: 2026-09-08
**Status**: done

**Notes**:

- `RoomAudioPublisher` gains: the keyword calling convention
  (`livekit_url`/`token`/`track_name`/`queue_size_ms`/`on_failure`), a real
  `flush()`, `wait_for_playout()`, `identity`, `track_sid`, `failed`,
  `_report_failure`, `_watch_disconnect`, `_clear_native_queue`, `_guarded`, and the
  module-level `_identity_from_token` / `_invoke` helpers plus the `FAILURE_CAPTURE` /
  `FAILURE_DISCONNECTED` reason codes.
- Tests: `pytest .../test_room_audio_publisher.py -q` → **26 passed** (8 pre-existing +
  18 new). Whole `tests/integrations/liveavatar/` → **199 passed**. `ruff check` clean.
- **The headline fix**: `flush()` now calls `AudioSource.clear_queue()`. The baseline
  only toggled a Python flag, so an "interrupt" left everything already handed to the
  SDK to play out — i.e. the previous turn kept speaking. Spec §6 lists this explicitly
  under Does-NOT-Exist. `test_flush_clears_native_queue` pins the call count.
- **`wait_for_playout` is deliberately separate from `flush`.** Spec §2: "never wait for
  stale audio during cancellation." Waiting is for normal turn completion; cancellation
  and handoff use `flush`, which *discards* that audio. Conflating them would reintroduce
  the stale-speech bug from the other direction. The docstring says so at the call site.
- **Failures are propagated, not swallowed.** A `capture_frame` exception now latches
  `failed = True`, makes subsequent `capture_pcm` no-ops, and fires
  `on_failure("capture_failed")` exactly once. The baseline logged and carried on, which
  is how a dead sink keeps looking alive to the broadcast session. `on_failure` is
  awaited *outside* the `try` that captures, so an observer's own exception cannot be
  mistaken for another capture failure. Room disconnect wires
  `on_failure("room_disconnected")` through `room.on("disconnected")`, guarded because
  fakes need not implement `on` and only registered when an observer exists.
- **Verified the installed SDK before using it** rather than trusting the task text:
  `unpublish_track(track_sid: str)` (so `start` now stores the `sid` from the
  `LocalTrackPublication` that `publish_track` returns), `AudioSource(sample_rate,
  num_channels, queue_size_ms=1000)`, `clear_queue() -> None` (sync),
  `wait_for_playout()` (async), and `AudioSource.aclose` exists while `close` does not.
- `aclose()` order is purge → unpublish → `source.aclose()` → `room.disconnect()`. The
  purge happens *before* `_closed` flips, otherwise `_clear_native_queue` would be
  skipped and queued audio could play out after teardown claimed to be done. Every step
  goes through `_guarded`, and `test_aclose_continues_past_a_failing_step` proves a
  failing unpublish does not strand the room connection.
- `identity` is decoded from the token's `sub` with no signature verification (same
  approach as `test_room_manager.py`'s `_jwt_payload`) purely for logging/inspection —
  no security decision reads it — and it is `None` for an undecodable token. The token
  itself is never logged.
- Legacy `start(tokens)` is unchanged: same `agent_token`, same `agent-voice` track name.
  `test_legacy_start_still_uses_agent_token_and_track` and the pre-existing
  `test_start_connects_with_agent_token_and_publishes_track` both pin it.
- Extended the shared test fakes as the task directed: `_FakeAudioSource` now takes
  `queue_size_ms` and exposes `clear_queue_calls`, `aclose_calls`, `capture_error` and a
  `playout_gate`; `_FakeLocalParticipant.publish_track` returns a `_FakePublication` with
  a `sid` and gains `unpublish_track`; `_FakeRoom` records `on()` subscriptions.

**Deviations from spec**: none.
