"""Floor authority and handoff-barrier tests (FEAT-537 TASK-2960).

Covers spec §2 "Moderation and exclusive speaking floor" and AC12–AC14 on the
server side: who may send microphone audio, and the ordering guarantee that
makes "never two live speakers" a property rather than a hope.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

from parrot.integrations.liveavatar.broadcast import (
    BroadcastDescriptor,
    BroadcastReason,
    FloorState,
    InMemoryBroadcastRegistry,
    ParticipantPrincipal,
    errors,
)
from parrot.integrations.liveavatar.broadcast.floor import (
    FLOOR_REVOKED,
    FLOOR_STATE,
    FloorCoordinator,
    validate_audio_authority,
)

TENANT = "acme"
AGENT = "agent-1"
BROADCAST = "bc-1"


class FakeClock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeSession:
    """A producer that records barriers and can refuse to acknowledge."""

    def __init__(self, *, fail: bool = False) -> None:
        self.switches: List[Tuple[str, int]] = []
        self.fail = fail

    async def switch_speaker(self, lease_id: str, floor_epoch: int) -> None:
        self.switches.append((lease_id, floor_epoch))
        if self.fail:
            raise errors.BroadcastError(
                BroadcastReason.STALE_FLOOR_EPOCH, message="barrier timed out"
            )


class RecordingNotifier:
    """Captures every control-socket notification, in order."""

    def __init__(self) -> None:
        self.sent: List[Tuple[str, Dict[str, Any]]] = []

    async def __call__(self, lease_id: str, frame: Dict[str, Any]) -> None:
        self.sent.append((lease_id, frame))

    def types_for(self, lease_id: str) -> List[str]:
        return [f["type"] for lid, f in self.sent if lid == lease_id]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def registry(clock: FakeClock) -> InMemoryBroadcastRegistry:
    return InMemoryBroadcastRegistry(clock=clock)


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def coordinator(notifier: RecordingNotifier) -> FloorCoordinator:
    return FloorCoordinator(notifier=notifier)


def _principal(user: str) -> ParticipantPrincipal:
    return ParticipantPrincipal(
        user_id=user, tenant_id=TENANT, agent_id=AGENT, display_name=user
    )


async def _seed(registry: InMemoryBroadcastRegistry, *names: str) -> Dict[str, Any]:
    """Create a broadcast and admit the named participants in order."""
    await registry.create(
        BroadcastDescriptor(
            broadcast_id=BROADCAST,
            tenant_id=TENANT,
            agent_id=AGENT,
            creator_user_id="creator",
        )
    )
    leases: Dict[str, Any] = {}
    for name in names:
        admission = await registry.reserve_viewer(
            TENANT, BROADCAST, _principal(name), f"identity-{name}"
        )
        await registry.confirm_viewer(TENANT, BROADCAST, admission.lease.lease_id)
        await registry.heartbeat_control(TENANT, BROADCAST, admission.lease.lease_id)
        leases[name] = admission.lease
    return leases


async def _lease(registry: InMemoryBroadcastRegistry, lease_id: str) -> Any:
    for lease in await registry.list_leases(TENANT, BROADCAST):
        if lease.lease_id == lease_id:
            return lease
    return None


# ── Authority validation ───────────────────────────────────────────────────


async def test_validate_audio_authority_accepts_the_current_speaker(
    registry: InMemoryBroadcastRegistry,
) -> None:
    leases = await _seed(registry, "moderator")
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    lease = await _lease(registry, leases["moderator"].lease_id)
    validate_audio_authority(
        descriptor, lease, floor_epoch=descriptor.floor_epoch, socket_id="sock-1"
    )


async def test_validate_audio_authority_rejects_non_speaker_and_stale_epoch(
    registry: InMemoryBroadcastRegistry,
) -> None:
    leases = await _seed(registry, "moderator", "guest")
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None

    guest = await _lease(registry, leases["guest"].lease_id)
    with pytest.raises(errors.FloorNotGranted):
        validate_audio_authority(
            descriptor, guest, floor_epoch=descriptor.floor_epoch, socket_id="sock-2"
        )

    moderator = await _lease(registry, leases["moderator"].lease_id)
    with pytest.raises(errors.StaleFloorEpoch):
        validate_audio_authority(
            descriptor, moderator, floor_epoch=descriptor.floor_epoch - 1,
            socket_id="sock-1",
        )


async def test_missing_floor_epoch_is_treated_as_stale(
    registry: InMemoryBroadcastRegistry,
) -> None:
    """An old client must not bypass fencing by omitting the field."""
    leases = await _seed(registry, "moderator")
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    lease = await _lease(registry, leases["moderator"].lease_id)
    with pytest.raises(errors.StaleFloorEpoch):
        validate_audio_authority(
            descriptor, lease, floor_epoch=None, socket_id="sock-1"
        )


async def test_missing_lease_is_rejected(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _seed(registry, "moderator")
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    with pytest.raises(errors.FloorNotGranted):
        validate_audio_authority(descriptor, None, floor_epoch=1, socket_id="sock-1")


async def test_a_second_socket_is_rejected(
    registry: InMemoryBroadcastRegistry,
) -> None:
    leases = await _seed(registry, "moderator")
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    lease_id = leases["moderator"].lease_id
    await registry.bind_speaker_socket(
        TENANT, BROADCAST, lease_id, "sock-1", descriptor.floor_epoch
    )
    lease = await _lease(registry, lease_id)
    with pytest.raises(errors.SpeakerConnectionExists):
        validate_audio_authority(
            descriptor, lease, floor_epoch=descriptor.floor_epoch, socket_id="sock-2"
        )


async def test_stale_control_heartbeat_refuses_audio(
    registry: InMemoryBroadcastRegistry, clock: FakeClock
) -> None:
    """Uncertain control ownership fails closed rather than admitting audio."""
    leases = await _seed(registry, "moderator")
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    lease = await _lease(registry, leases["moderator"].lease_id)
    # Fresh: fine.
    validate_audio_authority(
        descriptor, lease, floor_epoch=descriptor.floor_epoch, socket_id="s",
        now=clock(),
    )
    with pytest.raises(errors.FloorNotGranted, match="heartbeat"):
        validate_audio_authority(
            descriptor, lease, floor_epoch=descriptor.floor_epoch, socket_id="s",
            now=clock() + 20.0,
        )


async def test_no_audio_accepted_while_switching(
    registry: InMemoryBroadcastRegistry,
) -> None:
    """The whole barrier window is closed to BOTH participants."""
    leases = await _seed(registry, "moderator", "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        leases["moderator"].lease_id,
        leases["guest"].lease_id,
        current.version,
    )
    for name in ("moderator", "guest"):
        lease = await _lease(registry, leases[name].lease_id)
        with pytest.raises(errors.FloorNotGranted):
            validate_audio_authority(
                switching, lease, floor_epoch=switching.floor_epoch, socket_id="s"
            )


# ── Handoff barrier ────────────────────────────────────────────────────────


async def test_handoff_orders_switching_barrier_commit(
    registry: InMemoryBroadcastRegistry,
    coordinator: FloorCoordinator,
    notifier: RecordingNotifier,
) -> None:
    """grant → revoke notice → producer barrier → commit, in that order."""
    leases = await _seed(registry, "moderator", "guest")
    session = FakeSession()
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None

    result = await coordinator.handoff(
        registry,
        session,
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        moderator_lease_id=leases["moderator"].lease_id,
        target_lease_id=leases["guest"].lease_id,
        expected_version=current.version,
    )

    assert result.previous_speaker_lease_id == leases["moderator"].lease_id
    assert result.descriptor.floor_state is FloorState.GRANTED
    assert result.descriptor.speaker_lease_id == leases["guest"].lease_id
    assert result.floor_epoch == current.floor_epoch + 1

    # The producer was asked to fence at the NEW epoch, before the commit.
    assert session.switches == [(leases["guest"].lease_id, current.floor_epoch + 1)]

    # The outgoing speaker was told to stop; the incoming one was told it may.
    assert notifier.types_for(leases["moderator"].lease_id) == [FLOOR_REVOKED]
    assert notifier.types_for(leases["guest"].lease_id) == [FLOOR_STATE]
    assert notifier.sent[0][1]["floor_epoch"] == current.floor_epoch + 1


async def test_handoff_barrier_timeout_leaves_floor_idle(
    registry: InMemoryBroadcastRegistry, coordinator: FloorCoordinator
) -> None:
    """A failed barrier means silence plus a retryable error — not two speakers."""
    leases = await _seed(registry, "moderator", "guest")
    session = FakeSession(fail=True)
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None

    with pytest.raises(errors.BroadcastError) as excinfo:
        await coordinator.handoff(
            registry,
            session,
            tenant_id=TENANT,
            broadcast_id=BROADCAST,
            moderator_lease_id=leases["moderator"].lease_id,
            target_lease_id=leases["guest"].lease_id,
            expected_version=current.version,
        )
    assert excinfo.value.reason is BroadcastReason.STALE_FLOOR_EPOCH
    assert "retry" in str(excinfo.value)

    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.floor_state is FloorState.IDLE
    assert descriptor.speaker_lease_id is None

    # Neither participant may speak.
    for name in ("moderator", "guest"):
        lease = await _lease(registry, leases[name].lease_id)
        with pytest.raises(errors.FloorNotGranted):
            validate_audio_authority(
                descriptor, lease, floor_epoch=descriptor.floor_epoch, socket_id="s"
            )


async def test_only_the_moderator_can_hand_off(
    registry: InMemoryBroadcastRegistry, coordinator: FloorCoordinator
) -> None:
    leases = await _seed(registry, "moderator", "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    with pytest.raises(errors.NotModerator):
        await coordinator.handoff(
            registry,
            FakeSession(),
            tenant_id=TENANT,
            broadcast_id=BROADCAST,
            moderator_lease_id=leases["guest"].lease_id,
            target_lease_id=leases["guest"].lease_id,
            expected_version=current.version,
        )


async def test_concurrent_handoffs_conflict(
    registry: InMemoryBroadcastRegistry, coordinator: FloorCoordinator
) -> None:
    leases = await _seed(registry, "moderator", "a", "b")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    await coordinator.handoff(
        registry,
        FakeSession(),
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        moderator_lease_id=leases["moderator"].lease_id,
        target_lease_id=leases["a"].lease_id,
        expected_version=current.version,
    )
    # Second grant re-using the stale version loses.
    with pytest.raises(errors.StaleVersion):
        await coordinator.handoff(
            registry,
            FakeSession(),
            tenant_id=TENANT,
            broadcast_id=BROADCAST,
            moderator_lease_id=leases["moderator"].lease_id,
            target_lease_id=leases["b"].lease_id,
            expected_version=current.version,
        )


async def test_revoke_returns_the_floor_to_the_moderator(
    registry: InMemoryBroadcastRegistry, coordinator: FloorCoordinator
) -> None:
    leases = await _seed(registry, "moderator", "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    granted = await coordinator.handoff(
        registry,
        FakeSession(),
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        moderator_lease_id=leases["moderator"].lease_id,
        target_lease_id=leases["guest"].lease_id,
        expected_version=current.version,
    )
    back = await coordinator.handoff(
        registry,
        FakeSession(),
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        moderator_lease_id=leases["moderator"].lease_id,
        target_lease_id=None,
        expected_version=granted.descriptor.version,
    )
    assert back.descriptor.speaker_lease_id == leases["moderator"].lease_id


async def test_release_hands_the_floor_back_through_the_same_barrier(
    registry: InMemoryBroadcastRegistry,
    coordinator: FloorCoordinator,
    notifier: RecordingNotifier,
) -> None:
    leases = await _seed(registry, "moderator", "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    await coordinator.handoff(
        registry,
        FakeSession(),
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        moderator_lease_id=leases["moderator"].lease_id,
        target_lease_id=leases["guest"].lease_id,
        expected_version=current.version,
    )
    session = FakeSession()
    result = await coordinator.release(
        registry,
        session,
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        speaker_lease_id=leases["guest"].lease_id,
    )
    assert result.descriptor.speaker_lease_id == leases["moderator"].lease_id
    assert session.switches == [(leases["moderator"].lease_id, result.floor_epoch)]
    assert FLOOR_REVOKED in notifier.types_for(leases["guest"].lease_id)


async def test_release_by_a_non_speaker_is_refused(
    registry: InMemoryBroadcastRegistry, coordinator: FloorCoordinator
) -> None:
    leases = await _seed(registry, "moderator", "guest")
    with pytest.raises(errors.NotSpeaker):
        await coordinator.release(
            registry,
            FakeSession(),
            tenant_id=TENANT,
            broadcast_id=BROADCAST,
            speaker_lease_id=leases["guest"].lease_id,
        )


async def test_moderator_succession_completes_the_election_barrier(
    registry: InMemoryBroadcastRegistry, coordinator: FloorCoordinator
) -> None:
    """Election opens the barrier atomically; the producer closes it."""
    leases = await _seed(registry, "moderator", "second")
    outcome = await registry.release_viewer(
        TENANT, BROADCAST, leases["moderator"].lease_id
    )
    assert outcome.new_moderator == leases["second"].lease_id

    switching = await registry.get(TENANT, BROADCAST)
    assert switching is not None
    assert switching.floor_state is FloorState.SWITCHING

    session = FakeSession()
    result = await coordinator.succeed_moderator(
        registry,
        session,
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        new_moderator_lease_id=leases["second"].lease_id,
        floor_epoch=switching.floor_epoch,
        previous_speaker=leases["moderator"].lease_id,
    )
    assert result.descriptor.speaker_lease_id == leases["second"].lease_id
    assert result.descriptor.moderator_lease_id == leases["second"].lease_id
    assert session.switches == [(leases["second"].lease_id, switching.floor_epoch)]


async def test_a_notifier_failure_cannot_break_a_handoff(
    registry: InMemoryBroadcastRegistry,
) -> None:
    """Notifications are advisory; the durable state is authoritative."""

    async def _boom(_lease_id: str, _frame: Dict[str, Any]) -> None:
        raise RuntimeError("socket already gone")

    coordinator = FloorCoordinator(notifier=_boom)
    leases = await _seed(registry, "moderator", "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    result = await coordinator.handoff(
        registry,
        FakeSession(),
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        moderator_lease_id=leases["moderator"].lease_id,
        target_lease_id=leases["guest"].lease_id,
        expected_version=current.version,
    )
    assert result.descriptor.speaker_lease_id == leases["guest"].lease_id


async def test_handoff_without_a_local_producer_still_commits(
    registry: InMemoryBroadcastRegistry, coordinator: FloorCoordinator
) -> None:
    """``session=None`` means the producer is on another worker."""
    leases = await _seed(registry, "moderator", "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    result = await coordinator.handoff(
        registry,
        None,
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        moderator_lease_id=leases["moderator"].lease_id,
        target_lease_id=leases["guest"].lease_id,
        expected_version=current.version,
    )
    assert result.descriptor.speaker_lease_id == leases["guest"].lease_id


async def test_commit_failure_returns_the_floor_to_idle(
    registry: InMemoryBroadcastRegistry, coordinator: FloorCoordinator
) -> None:
    """A target that vanishes mid-barrier must not leave the floor switching."""
    leases = await _seed(registry, "moderator", "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None

    class _DepartingSession(FakeSession):
        async def switch_speaker(self, lease_id: str, floor_epoch: int) -> None:
            await super().switch_speaker(lease_id, floor_epoch)
            await registry.release_viewer(TENANT, BROADCAST, lease_id)

    with pytest.raises(errors.FloorNotGranted):
        await coordinator.handoff(
            registry,
            _DepartingSession(),
            tenant_id=TENANT,
            broadcast_id=BROADCAST,
            moderator_lease_id=leases["moderator"].lease_id,
            target_lease_id=leases["guest"].lease_id,
            expected_version=current.version,
        )
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.floor_state is FloorState.IDLE
    assert descriptor.speaker_lease_id is None
