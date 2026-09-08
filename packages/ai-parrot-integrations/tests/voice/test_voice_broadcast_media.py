"""Deterministic media, fallback and interruption tests for BroadcastSession.

FEAT-537 TASK-2958.  Everything vendor-facing is faked: the avatar session, the
direct publisher and the room manager.  The registry is the real in-memory
implementation from TASK-2952, so state transitions are exercised against the
same reference semantics the Redis backend reproduces.

These tests cover spec §2 "Audio routing, failure and interruption" and
AC5/AC6/AC7.  They are **not** evidence for those criteria: AC10 requires real
vendor media, and the TASK-2950 live gate did not run.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from parrot.integrations.liveavatar.broadcast import (
    BroadcastAudioFrame,
    BroadcastDescriptor,
    BroadcastReason,
    BroadcastSession,
    BroadcastState,
    InMemoryBroadcastRegistry,
    errors,
)
from parrot.integrations.liveavatar.broadcast.session import (
    DIRECT_TRACK_NAME,
    ROOM_CAPACITY,
)
from parrot.integrations.liveavatar.voice_session import AvatarStartupTimeout

TENANT = "acme"
AGENT = "agent-1"
BROADCAST = "bc-537-0001"


# ── Fakes ──────────────────────────────────────────────────────────────────


class FakeClock:
    """Injected monotonic clock for watchdog determinism."""

    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeAvatar:
    """Records the avatar-side calls and can stall or fail on demand."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.spoken: List[bytes] = []
        self.finish_calls = 0
        self.interrupt_calls = 0
        self.aclose_calls = 0
        self.speak_error: Optional[BaseException] = None
        self.speak_stall_s: Optional[float] = None
        self.liveavatar_session_id = "vendor-session-1"
        self.on_event = kwargs.get("on_event")
        self.on_close = kwargs.get("on_close")

    async def speak(self, pcm: bytes) -> None:
        if self.speak_stall_s is not None:
            await asyncio.sleep(self.speak_stall_s)
        if self.speak_error is not None:
            raise self.speak_error
        self.spoken.append(pcm)

    async def finish_turn(self) -> None:
        self.finish_calls += 1

    async def interrupt(self) -> None:
        self.interrupt_calls += 1

    async def aclose(self) -> None:
        self.aclose_calls += 1


class FakePublisher:
    """Records the direct-publisher calls."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.captured: List[bytes] = []
        self.flush_calls = 0
        self.aclose_calls = 0
        self.playout_calls = 0
        self.on_failure = kwargs.get("on_failure")

    async def capture_pcm(self, pcm: bytes) -> None:
        self.captured.append(pcm)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def wait_for_playout(self, timeout_s: Optional[float] = None) -> bool:
        self.playout_calls += 1
        return True

    async def aclose(self) -> None:
        self.aclose_calls += 1


class FakeRoomManager:
    """Records room/token operations without touching LiveKit."""

    def __init__(self, *, fail_mint_for: Optional[str] = None) -> None:
        self.url = "wss://fake.livekit.cloud"
        self.calls: List[tuple[str, Any]] = []
        self.fail_mint_for = fail_mint_for
        self.create_room_error: Optional[BaseException] = None

    async def create_room(self, room: str, *, max_participants: int = 12) -> None:
        self.calls.append(("create_room", (room, max_participants)))
        if self.create_room_error is not None:
            raise self.create_room_error

    def mint_publisher_token(self, room: str, identity: str, **_kw: Any) -> str:
        self.calls.append(("mint_publisher_token", identity))
        if self.fail_mint_for is not None and identity.startswith(self.fail_mint_for):
            raise RuntimeError("token minting failed")
        return f"token-for-{identity}"

    async def remove_participant(self, room: str, identity: str) -> None:
        self.calls.append(("remove_participant", identity))

    async def delete_room(self, room: str) -> None:
        self.calls.append(("delete_room", room))


class _Harness:
    """Bundles a session with the fakes it was built from."""

    def __init__(
        self,
        session: BroadcastSession,
        registry: InMemoryBroadcastRegistry,
        room_manager: FakeRoomManager,
        clock: FakeClock,
    ) -> None:
        self.session = session
        self.registry = registry
        self.room_manager = room_manager
        self.clock = clock
        self.avatars: List[FakeAvatar] = []
        self.publishers: List[FakePublisher] = []

    @property
    def avatar(self) -> FakeAvatar:
        return self.avatars[-1]

    @property
    def publisher(self) -> FakePublisher:
        return self.publishers[-1]

    def call_names(self) -> List[str]:
        return [name for name, _args in self.room_manager.calls]


def _descriptor(**kwargs: Any) -> BroadcastDescriptor:
    defaults: dict[str, Any] = {
        "broadcast_id": BROADCAST,
        "tenant_id": TENANT,
        "agent_id": AGENT,
        "creator_user_id": "creator",
        "voice_session_id": "conversation-1",
    }
    defaults.update(kwargs)
    return BroadcastDescriptor(**defaults)


def _frame(sequence: int, *, samples: int = 240, **overrides: Any) -> BroadcastAudioFrame:
    """Build a valid fenced frame (240 samples = 10 ms at 24 kHz)."""
    payload: dict[str, Any] = {
        "owner_epoch": 1,
        "speaker_lease_id": "lease-a",
        "floor_epoch": 1,
        "turn_id": "turn-1",
        "output_epoch": 1,
        "sequence": sequence,
        "pcm": bytes([sequence % 251]) * (samples * 2),
        "sample_count": samples,
    }
    payload.update(overrides)
    return BroadcastAudioFrame(**payload)


async def _build(
    *,
    avatar_error: Optional[BaseException] = None,
    fail_mint_for: Optional[str] = None,
    descriptor: Optional[BroadcastDescriptor] = None,
    **session_kwargs: Any,
) -> _Harness:
    """Create a registry, claim ownership and build a session over fakes."""
    clock = FakeClock()
    registry = InMemoryBroadcastRegistry(clock=clock)
    desc = descriptor or _descriptor()
    await registry.create(desc)
    _claimed, owner_epoch = await registry.claim_owner(
        TENANT, desc.broadcast_id, "worker-a"
    )
    stored = await registry.get(TENANT, desc.broadcast_id)
    assert stored is not None

    room_manager = FakeRoomManager(fail_mint_for=fail_mint_for)
    harness = _Harness(None, registry, room_manager, clock)  # type: ignore[arg-type]

    async def _avatar_factory(**kwargs: Any) -> FakeAvatar:
        if avatar_error is not None:
            raise avatar_error
        avatar = FakeAvatar(**kwargs)
        harness.avatars.append(avatar)
        return avatar

    async def _publisher_factory(**kwargs: Any) -> FakePublisher:
        publisher = FakePublisher(**kwargs)
        harness.publishers.append(publisher)
        return publisher

    harness.session = BroadcastSession(
        stored,
        registry,
        room_manager,  # type: ignore[arg-type]
        "worker-a",
        owner_epoch,
        avatar_session_factory=_avatar_factory,
        publisher_factory=_publisher_factory,
        clock=clock,
        **session_kwargs,
    )
    # The frames in these tests are fenced at floor_epoch 1.
    harness.session.floor_epoch = 1
    return harness


async def _settle() -> None:
    """Let the pump run."""
    for _ in range(20):
        await asyncio.sleep(0)


# ── Startup ────────────────────────────────────────────────────────────────


async def test_startup_allocates_room_and_direct_publisher_before_avatar() -> None:
    """The audience's fallback path must exist before the avatar is attempted."""
    harness = await _build()
    state = await harness.session.start()
    try:
        assert state is BroadcastState.AVATAR
        assert harness.call_names() == [
            "create_room",
            "mint_publisher_token",  # direct
            "mint_publisher_token",  # avatar
        ]
        # Direct publisher token is minted (and the publisher started) BEFORE
        # the avatar's token exists at all.
        identities = [
            args for name, args in harness.room_manager.calls
            if name == "mint_publisher_token"
        ]
        assert identities[0].startswith("direct-")
        assert identities[1].startswith("avatar-")
        assert identities[0] != identities[1]

        _room, max_participants = harness.room_manager.calls[0][1]
        assert max_participants == ROOM_CAPACITY == 12

        assert harness.publisher.kwargs["track_name"] == DIRECT_TRACK_NAME
        assert harness.publisher.kwargs["token"] == f"token-for-{identities[0]}"
        assert harness.avatar.kwargs["avatar_publisher_token"] == (
            f"token-for-{identities[1]}"
        )
        assert harness.avatar.kwargs["broadcast"] is True
        assert harness.session.output_epoch == 1
    finally:
        await harness.session.aclose()


@pytest.mark.parametrize(
    ("fail_at", "error", "expected_reason"),
    [
        ("token", None, BroadcastReason.AVATAR_CONTROL_LOST),
        ("start", RuntimeError("vendor 500"), BroadcastReason.AVATAR_CONTROL_LOST),
        ("ws_gate", RuntimeError("connected gate"), BroadcastReason.AVATAR_CONTROL_LOST),
        (
            "deadline",
            AvatarStartupTimeout("too slow"),
            BroadcastReason.AVATAR_STARTUP_TIMEOUT,
        ),
    ],
)
async def test_avatar_failure_at_each_stage_falls_back_to_audio_only(
    fail_at: str, error: Optional[BaseException], expected_reason: BroadcastReason
) -> None:
    """Every avatar startup failure degrades; none of them reaches the caller."""
    harness = await _build(
        avatar_error=error,
        fail_mint_for="avatar-" if fail_at == "token" else None,
    )
    state = await harness.session.start()  # must not raise
    try:
        assert state is BroadcastState.AUDIO_ONLY
        assert harness.session.failure_reason is expected_reason
        # The publisher is alive and is now the authoritative sink.
        assert harness.publisher.aclose_calls == 0
        descriptor = await harness.registry.get(TENANT, BROADCAST)
        assert descriptor is not None
        assert descriptor.state is BroadcastState.AUDIO_ONLY
        assert descriptor.failure_reason is expected_reason

        await harness.session.push_audio(_frame(0, output_epoch=1))
        await _settle()
        assert harness.publisher.captured
    finally:
        await harness.session.aclose()


async def test_livekit_prerequisite_failure_is_failed_not_fallback() -> None:
    """AC7: a fatal LiveKit failure must never be reported as a working fallback."""
    harness = await _build()
    harness.room_manager.create_room_error = RuntimeError("livekit unreachable")
    with pytest.raises(RuntimeError, match="livekit unreachable"):
        await harness.session.start()
    descriptor = await harness.registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.state is BroadcastState.FAILED
    assert descriptor.failure_reason is BroadcastReason.LIVEKIT_FAILURE


async def test_direct_publisher_failure_aborts_the_broadcast() -> None:
    """There is no sink below the direct publisher."""
    harness = await _build()
    await harness.session.start()
    await harness.publisher.on_failure("capture_failed")
    descriptor = await harness.registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.state is BroadcastState.FAILED
    assert descriptor.failure_reason is BroadcastReason.LIVEKIT_FAILURE


# ── Routing ────────────────────────────────────────────────────────────────


async def test_avatar_mode_routes_only_to_the_avatar() -> None:
    """Exactly one audible source: clients must never get two."""
    harness = await _build()
    await harness.session.start()
    try:
        for index in range(3):
            await harness.session.push_audio(_frame(index))
        await _settle()
        assert len(harness.avatar.spoken) == 3
        assert harness.publisher.captured == []
    finally:
        await harness.session.aclose()


async def test_stale_frames_are_dropped_and_counted() -> None:
    harness = await _build()
    await harness.session.start()
    try:
        await harness.session.push_audio(_frame(0, output_epoch=99))
        await harness.session.push_audio(_frame(1, floor_epoch=99))
        await harness.session.push_audio(_frame(2, owner_epoch=99))
        await _settle()
        assert harness.avatar.spoken == []
        assert harness.session.dropped_stale_frames == 3
    finally:
        await harness.session.aclose()


async def test_queue_never_exceeds_the_byte_budget() -> None:
    """Bounded queue: a stalled avatar cuts over rather than accumulating."""
    harness = await _build(max_queued_bytes=2_000, send_deadline_s=0.05)
    session = harness.session
    await session.start()
    try:
        harness.avatar.speak_stall_s = 5.0
        for index in range(20):
            await session.push_audio(_frame(index, samples=240))
            # The invariant that matters: the budget is never breached, even
            # while the sink is wedged.
            assert session.queued_bytes <= 2_000
            if session.state is BroadcastState.AUDIO_ONLY:
                break
            await _settle()
        assert session.state is BroadcastState.AUDIO_ONLY
        assert session.dropped_overflow_frames >= 1
    finally:
        await session.aclose()


async def test_direct_sink_overflow_aborts_the_turn() -> None:
    """AC: with nowhere left to fall, the turn fails loudly rather than lagging."""
    harness = await _build(
        max_queued_bytes=1_000, avatar_error=RuntimeError("no avatar")
    )
    state = await harness.session.start()
    assert state is BroadcastState.AUDIO_ONLY
    try:
        # Stop the pump draining so the queue can actually fill.
        assert harness.session._pump_task is not None  # noqa: SLF001
        harness.session._pump_task.cancel()  # noqa: SLF001
        with pytest.raises(errors.BroadcastError) as excinfo:
            for index in range(20):
                await harness.session.push_audio(_frame(index, samples=240))
        assert excinfo.value.reason is BroadcastReason.LIVEKIT_FAILURE
        assert harness.session.queued_bytes == 0
    finally:
        await harness.session.aclose()


# ── Cutover ────────────────────────────────────────────────────────────────


async def test_cutover_forwards_only_unsubmitted_frames() -> None:
    """Queued frames are saved; the in-flight (ambiguous) one is not replayed."""
    harness = await _build(send_deadline_s=0.05)
    await harness.session.start()
    try:
        harness.avatar.speak_stall_s = 5.0  # first frame will hang, then time out
        for index in range(4):
            await harness.session.push_audio(_frame(index, samples=240))
        # Let the pump pick up frame 0 and hit the send deadline.
        await asyncio.sleep(0.15)
        await _settle()

        assert harness.session.state is BroadcastState.AUDIO_ONLY
        assert harness.session.output_epoch == 2
        # Frame 0 was in flight when the deadline fired: ambiguous, dropped.
        assert harness.session.dropped_ambiguous_samples == 240
        assert harness.avatar.spoken == []
        # Frames 1..3 were never submitted, so they are re-routed.
        assert harness.session.forwarded_on_cutover == 3
        await _settle()
        assert len(harness.publisher.captured) == 3
    finally:
        await harness.session.aclose()


async def test_control_socket_close_triggers_a_single_cutover() -> None:
    harness = await _build()
    await harness.session.start()
    try:
        on_close = harness.avatar.on_close
        assert on_close is not None
        await on_close("close")
        await on_close("close")  # idempotent — one-way
        assert harness.session.state is BroadcastState.AUDIO_ONLY
        assert harness.session.output_epoch == 2
        assert harness.avatar.aclose_calls == 1
        assert ("remove_participant", harness.session.avatar_identity) in (
            harness.room_manager.calls
        )
    finally:
        await harness.session.aclose()


async def test_vendor_fatal_event_triggers_cutover() -> None:
    harness = await _build()
    await harness.session.start()
    try:
        on_event = harness.avatar.on_event
        assert on_event is not None
        await on_event({"type": "session.error", "message": "boom"})
        assert harness.session.state is BroadcastState.AUDIO_ONLY
        assert harness.session.failure_reason is BroadcastReason.AVATAR_CONTROL_LOST
    finally:
        await harness.session.aclose()


async def test_avatar_participant_loss_triggers_cutover() -> None:
    harness = await _build()
    await harness.session.start()
    try:
        await harness.session.on_participant_disconnected("some-viewer")
        assert harness.session.state is BroadcastState.AVATAR
        await harness.session.on_participant_disconnected(
            harness.session.avatar_identity
        )
        assert harness.session.state is BroadcastState.AUDIO_ONLY
        assert harness.session.failure_reason is BroadcastReason.AVATAR_TRACK_LOST
    finally:
        await harness.session.aclose()


async def test_speech_progress_watchdog_cuts_over() -> None:
    """No vendor progress while speech was expected — but idle is not failure."""
    harness = await _build(speech_watchdog_s=10.0)
    session = harness.session
    await session.start()
    try:
        # Nothing sent yet → idle, never a failure.
        assert session._check_speech_watchdog() is False  # noqa: SLF001

        await session.push_audio(_frame(0))
        await _settle()
        assert session._check_speech_watchdog() is False  # noqa: SLF001

        # Frames were sent recently but the vendor went quiet.
        harness.clock.advance(11.0)
        assert session._check_speech_watchdog() is False  # noqa: SLF001 (now idle)

        session._last_frame_sent_at = harness.clock()  # noqa: SLF001
        session._last_speech_event_at = harness.clock() - 11.0  # noqa: SLF001
        assert session._check_speech_watchdog() is True  # noqa: SLF001
    finally:
        await session.aclose()


async def test_a_speaking_event_resets_the_watchdog() -> None:
    harness = await _build()
    await harness.session.start()
    try:
        on_event = harness.avatar.on_event
        assert on_event is not None
        harness.clock.advance(5.0)
        await on_event({"type": "agent.speak_started"})
        assert harness.session._last_speech_event_at == harness.clock()  # noqa: SLF001
    finally:
        await harness.session.aclose()


async def test_stale_avatar_event_cannot_recover() -> None:
    """audio_only is sticky: no late avatar event may restore avatar mode."""
    harness = await _build()
    await harness.session.start()
    try:
        on_close = harness.avatar.on_close
        on_event = harness.avatar.on_event
        assert on_close is not None and on_event is not None
        await on_close("close")
        assert harness.session.state is BroadcastState.AUDIO_ONLY
        epoch_after_cutover = harness.session.output_epoch

        # Every kind of late avatar signal.
        await on_event({"type": "agent.speak_started"})
        await on_event({"type": "session.state_updated", "state": "connected"})
        await on_event({"type": "session.error"})
        await harness.session.on_participant_disconnected(
            harness.session.avatar_identity
        )

        assert harness.session.state is BroadcastState.AUDIO_ONLY
        assert harness.session.output_epoch == epoch_after_cutover

        # And audio still flows, to the direct sink only.
        await harness.session.push_audio(
            _frame(9, output_epoch=harness.session.output_epoch)
        )
        await _settle()
        assert harness.publisher.captured
        assert harness.avatar.spoken == []
    finally:
        await harness.session.aclose()


# ── Interruption and handoff ───────────────────────────────────────────────


async def test_interrupt_clears_software_and_native_queues() -> None:
    """All three layers: deque, vendor, and the native AudioSource queue."""
    harness = await _build(send_deadline_s=1.0)
    await harness.session.start()
    try:
        harness.avatar.speak_stall_s = 0.5  # keep the pump busy
        for index in range(5):
            await harness.session.push_audio(_frame(index))
        assert harness.session.queued_bytes > 0

        await harness.session.interrupt()
        assert harness.session.queued_bytes == 0
        assert harness.avatar.interrupt_calls == 1
        # flush() is a real clear_queue since TASK-2956 — the Python deque
        # alone is not enough.
        assert harness.publisher.flush_calls == 1
    finally:
        await harness.session.aclose()


async def test_interrupt_drops_frames_from_the_previous_generation() -> None:
    harness = await _build(send_deadline_s=1.0)
    session = harness.session
    await session.start()
    try:
        harness.avatar.speak_stall_s = 0.3
        for index in range(4):
            await session.push_audio(_frame(index))
        await session.interrupt()
        await _settle()
        # At most the single in-flight frame can have been spoken.
        assert len(harness.avatar.spoken) <= 1
    finally:
        await session.aclose()


async def test_switch_speaker_runs_the_barrier_and_is_acknowledged() -> None:
    harness = await _build()
    session = harness.session
    await session.start()
    try:
        await session.push_audio(_frame(0))
        await _settle()
        await session.switch_speaker("lease-b", floor_epoch=2)
        assert session.floor_epoch == 2
        assert harness.avatar.interrupt_calls == 1
        assert harness.publisher.flush_calls == 1

        # Old-epoch audio is rejected after the barrier.
        await session.push_audio(_frame(1, floor_epoch=1))
        await _settle()
        assert session.dropped_stale_frames >= 1
        # New-epoch audio flows.
        before = len(harness.avatar.spoken)
        await session.push_audio(_frame(2, floor_epoch=2))
        await _settle()
        assert len(harness.avatar.spoken) == before + 1
    finally:
        await session.aclose()


async def test_switch_speaker_barrier_times_out() -> None:
    """A dead pump must fail the handoff, never install a second speaker."""
    harness = await _build()
    session = harness.session
    await session.start()
    try:
        assert session._pump_task is not None  # noqa: SLF001
        session._pump_task.cancel()  # noqa: SLF001
        await asyncio.sleep(0)

        import parrot.integrations.liveavatar.broadcast.session as session_module

        original = session_module.HANDOFF_BARRIER_TIMEOUT_S
        session_module.HANDOFF_BARRIER_TIMEOUT_S = 0.05
        try:
            with pytest.raises(errors.BroadcastError) as excinfo:
                await session.switch_speaker("lease-b", floor_epoch=2)
        finally:
            session_module.HANDOFF_BARRIER_TIMEOUT_S = original
        assert excinfo.value.reason is BroadcastReason.STALE_FLOOR_EPOCH
    finally:
        await session.aclose()


async def test_finish_turn_uses_the_active_sink() -> None:
    harness = await _build()
    session = harness.session
    await session.start()
    try:
        await session.push_audio(_frame(0))
        await session.finish_turn("turn-1")
        assert harness.avatar.finish_calls == 1
        assert harness.publisher.playout_calls == 0

        await harness.avatar.on_close("close")
        await session.finish_turn("turn-2")
        # After fallback, completion waits on the direct publisher instead.
        assert harness.publisher.playout_calls == 1
    finally:
        await session.aclose()


# ── Ownership and teardown ─────────────────────────────────────────────────


async def test_owner_renew_failure_stops_publishing() -> None:
    """Fail closed: a fenced producer stops before two producers can overlap."""
    harness = await _build()
    session = harness.session
    await session.start()

    async def _refuse(*_args: Any, **_kwargs: Any) -> bool:
        return False

    harness.registry.renew_owner = _refuse  # type: ignore[method-assign]
    assert await session._renew_owner() is False  # noqa: SLF001

    assert session.closed is True
    assert session.state is BroadcastState.FAILED
    assert session.failure_reason is BroadcastReason.OWNER_LOST
    assert harness.avatar.aclose_calls == 1
    assert harness.publisher.aclose_calls == 1

    descriptor = await harness.registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.state is BroadcastState.FAILED
    assert descriptor.failure_reason is BroadcastReason.OWNER_LOST

    # And it really stopped publishing.
    await session.push_audio(_frame(0))
    await _settle()
    assert harness.avatar.spoken == []


async def test_stop_request_tears_the_producer_down() -> None:
    harness = await _build()
    session = harness.session
    await session.start()
    admission = await harness.registry.reserve_viewer(
        TENANT, BROADCAST, _principal(), "identity-mod"
    )
    await harness.registry.request_stop(TENANT, BROADCAST, admission.lease.lease_id)
    assert await session._stop_requested() is True  # noqa: SLF001


def _principal() -> Any:
    from parrot.integrations.liveavatar.broadcast import ParticipantPrincipal

    return ParticipantPrincipal(user_id="u", tenant_id=TENANT, agent_id=AGENT)


async def test_aclose_idempotent_and_releases_everything() -> None:
    harness = await _build()
    session = harness.session
    await session.start()
    await session.aclose()
    await session.aclose()

    assert harness.avatar.aclose_calls == 1
    assert harness.avatar.interrupt_calls == 1
    assert harness.publisher.aclose_calls == 1
    assert ("delete_room", session.room_name) in harness.room_manager.calls
    assert session.closed is True
    descriptor = await harness.registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.state is BroadcastState.ENDED


async def test_aclose_before_start_is_safe() -> None:
    """Cancellation during startup must leave nothing open."""
    harness = await _build()
    await harness.session.aclose()
    assert harness.session.closed is True
    assert harness.avatars == []
    assert harness.publishers == []


async def test_aclose_after_a_partial_startup_closes_the_publisher() -> None:
    harness = await _build(avatar_error=RuntimeError("no avatar"))
    await harness.session.start()
    await harness.session.aclose()
    assert harness.publisher.aclose_calls == 1
    assert harness.avatars == []


async def test_push_after_close_is_a_noop() -> None:
    harness = await _build()
    await harness.session.start()
    await harness.session.aclose()
    await harness.session.push_audio(_frame(0))
    assert harness.session.queued_bytes == 0


# ── Media state projection ─────────────────────────────────────────────────


async def test_media_state_is_credential_free() -> None:
    harness = await _build()
    await harness.session.start()
    try:
        state = harness.session.media_state()
        assert state["room_name"] == harness.session.room_name
        assert state["avatar_identity"].startswith("avatar-")
        assert state["direct_identity"].startswith("direct-")
        assert state["liveavatar_session_id"] == "vendor-session-1"
        blob = str(state).lower()
        for fragment in ("token", "secret", "ws_url", "api_key"):
            assert fragment not in blob
    finally:
        await harness.session.aclose()
