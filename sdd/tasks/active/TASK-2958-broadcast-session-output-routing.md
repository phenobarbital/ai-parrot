# TASK-2958: BroadcastSession — producer lifecycle, output routing, fallback and interruption

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2950, TASK-2952, TASK-2954, TASK-2955, TASK-2956, TASK-2957
**Parallel**: false
**Parallelism notes**: Central media object; consumes every Module 2/3 extension. Creates `broadcast/session.py` + `test_voice_broadcast_media.py` only. TASK-2950 dependency is the spec's live gate: if TASK-2950 finished `done-with-issues` (NOT RUN), implement against the spec defaults and make every vendor-dependent threshold a constructor knob.

---

## Context

Spec §2 "Architectural Design" + "Audio routing, failure and interruption" (Module 3): one broadcast owns one Nova VoiceBot conversation, one LiveAvatar generation session and one LiveKit output room. Allocate room + **silent direct publisher first**, then attempt the avatar with a 15 s readiness deadline; on failure move irreversibly to `audio_only`. Bounded PCM queue (≤ 96 000 B ≈ 2 s at 24 kHz mono PCM16) separates Nova production from vendor sends. Interrupt/handoff clears software queues **and** the native `AudioSource` queue.

## Scope

- `broadcast/session.py`: `class BroadcastSession` with the public API from spec §2: `start()`, `push_audio(frame: BroadcastAudioFrame)`, `finish_turn(turn_id)`, `switch_speaker(new_speaker_lease_id, floor_epoch) -> None` (the producer-side barrier: cancel/interrupt old turn, clear queues, `AudioSource.clear_queue()`, bump `turn_generation`, then ack), `interrupt(reason)`, `aclose()`. Constructor takes: `descriptor: BroadcastDescriptor`, `registry: BroadcastRegistry`, `room_manager: LiveKitRoomManager`, `worker_id: str`, `owner_epoch: int`, `avatar_session_factory` (default `VoiceAvatarSession.start`), `publisher_factory` (default `RoomAudioPublisher.start`), `clock`, and knobs `avatar_startup_deadline_s=15.0`, `speech_watchdog_s=10.0`, `send_deadline_s=2.0`, `max_queued_bytes=96_000`, `max_session_duration_s=600`.
- `start()` sequence: `registry.transition(starting)` → `room_manager.create_room(room, max_participants=12)` → mint `direct-<bid8>` publisher token → `RoomAudioPublisher.start(livekit_url, token, track_name="direct-voice", on_failure=...)` (silent) → mint `avatar-<bid8>` token → `VoiceAvatarSession.start(..., livekit_url, room_name, avatar_publisher_token, avatar_identity, broadcast=True, startup_deadline_s, on_event, on_close, max_session_duration_s)`; success ⇒ `transition(avatar, output_epoch+1, avatar_identity=..., direct_identity=...)`; any avatar failure/timeout ⇒ `transition(audio_only, reason=avatar_startup_timeout|…)`. Nova/LiveKit/Redis prerequisite failure ⇒ `transition(failed, reason=nova_failure|livekit_failure)` after cleanup — never labelled a fallback.
- Routing task (`_pump()`): consumes an `asyncio.Queue` of `BroadcastAudioFrame`s bounded by bytes; in `avatar` state sends only to `avatar_session.speak()`; in `audio_only` only to `publisher.capture_pcm()`; drops frames whose `output_epoch`/`turn_generation`/`floor_epoch` are stale (counts them). Backpressure policy (tested): avatar sink stalled beyond `send_deadline_s` ⇒ cutover to `audio_only`; direct sink cannot keep up ⇒ abort the turn with `BroadcastError(reason=livekit_failure)` for that turn, never accumulate indefinitely.
- Runtime fallback triggers → `_cutover(reason)`: `on_close` from the control WS, avatar participant/track loss (from a `on_participant_disconnected(identity)` hook the owner wires from a subscriber/room events in TASK-2961 or the watchdog), vendor fatal event (`on_event` type containing `error`), `AvatarSendTimeout`, speech-progress watchdog (no vendor speaking/progress event within `speech_watchdog_s` while frames were sent). Cutover atomically: `output_epoch += 1`, cancel in-flight avatar send, drop queued frames **already submitted**, forward retained **never-submitted** frames to the publisher, `avatar_session.aclose()` (also `room_manager.remove_participant(room, avatar_identity)`), `registry.transition(audio_only, output_epoch, reason)`. One-way: any later avatar event is ignored (`test_stale_avatar_event_cannot_recover`).
- `interrupt()` / `switch_speaker()`: cancel current turn generation, `avatar_session.interrupt()` (if avatar), clear queue, `publisher.flush()` (native `clear_queue`), bump generation; `switch_speaker` completes within `HANDOFF_BARRIER_TIMEOUT_S` or raises `BroadcastError(reason=stale_floor_epoch)`.
- `finish_turn()`: `avatar_session.finish_turn()` or `await publisher.wait_for_playout(timeout)` only at normal completion.
- Owner lease loop: renew every 5 s via `registry.renew_owner`; if renewal fails ⇒ stop publishing immediately and `aclose()` (`reason=owner_lost`). Stop poll: check `registry.stop_requested()` ≥ 1/s.
- `aclose()` idempotent, cancellation-safe at every startup stage: cancel pump → interrupt/stop avatar → close WS/client → `publisher.aclose()` (clears+closes source) → `room_manager.delete_room` when audience empty → `registry.transition(ended|failed)`.
- Tests `tests/voice/test_voice_broadcast_media.py` with fake avatar session / publisher / room manager / in-memory registry / fake clock.

**NOT in scope**: VoiceBot/handler integration (TASK-2959), floor authority validation at ingress (TASK-2960), worker relay (TASK-2961).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/session.py` | CREATE | `BroadcastSession` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/__init__.py` | MODIFY | Export |
| `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_media.py` | CREATE | Deterministic media/fallback/interrupt tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.broadcast.models import BroadcastDescriptor, BroadcastAudioFrame, BroadcastState, BroadcastReason, MAX_QUEUED_PCM_BYTES, AVATAR_STARTUP_DEADLINE_S, HANDOFF_BARRIER_TIMEOUT_S, OWNER_RENEW_S  # TASK-2951
from parrot.integrations.liveavatar.broadcast.registry import BroadcastRegistry            # TASK-2952
from parrot.integrations.liveavatar.broadcast.errors import BroadcastError                 # TASK-2952
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager                 # room_manager.py:47 (+ TASK-2954 mint_publisher_token/create_room/remove_participant/delete_room)
from parrot.integrations.liveavatar.room_audio_publisher import RoomAudioPublisher         # room_audio_publisher.py:68 (+ TASK-2956 start(livekit_url=,token=,track_name=,on_failure=), flush()→clear_queue, wait_for_playout)
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession                # voice_session.py:55 (+ TASK-2957 injected creds, on_event/on_close, startup_deadline_s)
from parrot.integrations.liveavatar.avatar_ws import AvatarSendTimeout                     # TASK-2955
```

### Existing Signatures to Use
```python
VoiceAvatarSession.speak(pcm: bytes) / finish_turn() / interrupt() / aclose()             # voice_session.py:223/235/243/252 (aclose idempotent, never raises)
RoomAudioPublisher.capture_pcm(pcm) / flush() / aclose()                                   # room_audio_publisher.py:170/205/221
# Nova output is 24 kHz mono PCM16 (audio.py:346 OUTPUT_SAMPLE_RATE_HZ = 24000); Nova interruption surfaces as LiveVoiceResponse.is_interrupted (models/voice.py:376)
```

### Does NOT Exist
- ~~`BroadcastSession`~~ — new. ~~`VoiceAvatarSession` events before TASK-2955/2957~~ — verify they landed.
- ~~Automatic `audio_only → avatar` recovery~~ — forbidden (spec Non-Goals).
- ~~Replaying frames already handed to the avatar WS~~ — forbidden ("never replay submitted PCM").
- ~~`max_participants=10` as seat enforcement~~ — seats are registry reservations; room capacity is 12.

## Implementation Notes

- Track `submitted_upto: int` (frame sequence) per turn; on cutover only frames with `sequence > submitted_upto` go to the publisher. Log `dropped_ambiguous_samples`.
- Use one `asyncio.Event` per barrier: `switch_speaker` sets `self._generation += 1`, awaits the pump to observe it (`await asyncio.wait_for(self._gen_ack.wait(), HANDOFF_BARRIER_TIMEOUT_S)`).
- All vendor sends inside `asyncio.wait_for(..., send_deadline_s)`.
- Emit structured log events (`broadcast_id`, `state`, `output_epoch`, `reason`) at INFO on every transition.

## Acceptance Criteria

- [ ] Startup order verified by fake call log: create_room → direct publisher start → avatar start; avatar failure at **each** stage (token/start/WS gate/deadline) ⇒ `audio_only`, publisher alive, no exception to caller.
- [ ] Queue never exceeds `max_queued_bytes`; stalled avatar send ⇒ cutover once; stalled publisher ⇒ turn aborted with `livekit_failure`.
- [ ] Runtime WS close / track loss / fatal event / watchdog ⇒ single cutover, `output_epoch` +1, never-submitted frames forwarded, submitted ones not replayed; late avatar event ignored.
- [ ] `interrupt()` and `switch_speaker()` call `avatar.interrupt()` (avatar mode) and `publisher.flush()` (→ `clear_queue`) and drop queued frames; barrier timeout raises.
- [ ] Owner renewal failure ⇒ publishing stops before lease expiry (fake clock), state `failed`/`reason=owner_lost`.
- [ ] `aclose()` idempotent; cancellation during startup leaves no live fakes open.
- [ ] `pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_media.py -q` green; `ruff check` clean.

## Test Specification

```python
class FakeAvatar:  # records speak/finish/interrupt/aclose, can raise/stall, exposes on_event/on_close triggers
class FakePublisher:  # capture_pcm/flush/aclose/wait_for_playout counters, clear_queue_calls, stall flag
class FakeRoomManager:  # create_room/mint_publisher_token/remove_participant/delete_room log

async def test_startup_allocates_room_and_direct_publisher_before_avatar(): ...
@pytest.mark.parametrize("fail_at", ["token", "start", "ws_gate", "deadline"])
async def test_avatar_failure_at_each_stage_falls_back_to_audio_only(fail_at): ...
async def test_cutover_forwards_only_unsubmitted_frames(): ...
async def test_stale_avatar_event_cannot_recover(): ...
async def test_interrupt_clears_software_and_native_queues(): ...
async def test_switch_speaker_barrier_times_out(): ...
async def test_owner_renew_failure_stops_publishing(): ...
async def test_aclose_idempotent_and_cancellation_safe(): ...
```

## Agent Instructions
1. Read spec §2 fully (Overview, End-to-end sequence steps 3/7/8, Audio routing section). 2. Verify TASK-2954–2957 APIs landed; read TASK-2950's report for confirmed event names. 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
