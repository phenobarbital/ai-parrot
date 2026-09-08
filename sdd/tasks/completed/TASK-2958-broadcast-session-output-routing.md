# TASK-2958: BroadcastSession — producer lifecycle, output routing, fallback and interruption

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: done
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

**Completed by**: `sdd-worker` (autonomous session)
**Date**: 2026-09-08
**Status**: done

**Notes**:

- Created `broadcast/session.py` (`BroadcastSession`, `ROOM_CAPACITY=12`,
  `STOP_POLL_S`, `DIRECT_TRACK_NAME="direct-voice"`), exported it from the package,
  and added `tests/voice/test_voice_broadcast_media.py`.
- Tests: `pytest .../test_voice_broadcast_media.py -q` → **30 passed**. Whole
  `tests/voice/` → **318 passed** (baseline was 137; the 11 failures / 27 errors are the
  same pre-existing environment ones — `ai-parrot-client-*` satellites are not installed
  in this venv). `ruff check` clean.
- **Startup order is asserted, not assumed**: the fake room manager's call log must read
  `create_room → mint(direct-…) → mint(avatar-…)`, and the two publisher identities must
  differ. `max_participants` is asserted `== ROOM_CAPACITY == 12` with the spec §7
  reason inline. The direct publisher exists before the avatar is even tokenised, so an
  avatar failure degrades in the room the audience already joined.
- **Avatar failure at all four stages is parametrised** (token mint, `start_session`,
  WS gate, startup deadline) — each selects `audio_only`, leaves the publisher alive,
  raises nothing at the caller, and is followed by an assertion that audio actually
  flows to the direct sink. Only the deadline maps to `avatar_startup_timeout`; the rest
  map to `avatar_control_lost`.
- **A LiveKit/room failure is `failed`, never a fallback** (AC7). `start()` re-raises
  after `_abort()`, and the descriptor shows `failed` / `livekit_failure`. Direct
  publisher failure does the same — there is no sink below it.
- **Ambiguity handling is the subtle part.** On cutover only frames still *in the deque*
  are re-routed; the frame whose send was in flight is counted in
  `dropped_ambiguous_samples` and dropped. `test_cutover_forwards_only_unsubmitted_frames`
  pins exactly that: 240 ambiguous samples dropped, 3 frames forwarded, nothing spoken
  twice. Retained frames are **re-stamped** with the new `output_epoch` — without that
  the pump would reject the very frames the cutover was trying to save.
- **`audio_only` is sticky**, verified against every late avatar signal
  (`agent.speak_started`, a fresh `connected`, a fatal error, participant loss):
  `test_stale_avatar_event_cannot_recover` asserts the state and `output_epoch` are
  unmoved and that audio still reaches only the direct sink.
- **The handoff barrier is acknowledged by the pump, not assumed.** `switch_speaker`
  bumps a generation and waits for the pump to observe it; a cancelled pump makes the
  barrier time out and raise `stale_floor_epoch`, so the caller leaves the floor idle
  rather than installing a second speaker (`test_switch_speaker_barrier_times_out`).
- **Bounded-queue policy needed a correction found by a failing test.** The first
  implementation re-offered the overflow frame through `push_audio` after cutting over —
  but the cutover has just refilled the queue with the retained backlog, so the recursive
  call saw a full queue in `audio_only` and aborted the turn, i.e. the fallback killed
  the speech it existed to save. It now appends directly if it fits and otherwise drops
  one frame: spec §2 accepts "a brief gap" at the cutover boundary but never unbounded
  accumulation. Sustained overflow in `audio_only` still aborts the turn with
  `livekit_failure`.
- `interrupt()` clears **all three** layers — deque, vendor (`avatar.interrupt()`), and
  the native `AudioSource` queue via `publisher.flush()` (a real `clear_queue` since
  TASK-2956). `finish_turn()` is the only place that *waits* for playout, and only on
  the active sink; spec §2 forbids waiting for stale audio during cancellation.
- Owner renewal failure closes the session immediately with `owner_lost` and the test
  proves publication really stopped (a later `push_audio` produces nothing). The owner
  loop also polls the stop flag at 1 Hz and runs the speech watchdog, which deliberately
  returns `False` when nothing was sent recently — idle silence is not failure (spec §2).
- Every vendor-timing threshold is a constructor knob (`avatar_startup_deadline_s`,
  `speech_watchdog_s`, `send_deadline_s`, `max_queued_bytes`, `max_session_duration_s`)
  because TASK-2950's live gate did **not** run; the module docstring says so.
- Avatar event *names* are matched by substring (`speak`, `error`/`fail`), never
  hard-coded, for the same reason.

**Deviations from spec — one, and it needs a follow-up decision:**

The task's Scope says `transition(avatar, output_epoch+1, avatar_identity=…,
direct_identity=…)`. **`BroadcastRegistry.transition` has no such parameters** — TASK-2952
defined it as `(tenant_id, broadcast_id, new_state, *, output_epoch, reason,
expected_owner_epoch)`, and TASK-2958's own Files table lists only `session.py`,
`__init__.py` and the test module, so adding them here would violate file fidelity (and
would also require re-writing TASK-2953's Lua `transition` script, well outside scope).

Resolution taken: the session owns `room_name` / `avatar_identity` / `direct_identity`
and exposes them through a credential-free `media_state()` snapshot (tested to contain no
`token`/`secret`/`ws_url`/`api_key`). **TASK-2961 (`BroadcastService`) or TASK-2962 must
persist these onto the descriptor**, otherwise `BroadcastPublicState.selected_identity`
and the selected track ids stay `None` and the browser policy in TASK-2964 has nothing to
select on. Flagging it here rather than silently widening another task's API.
