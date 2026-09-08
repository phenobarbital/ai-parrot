"""Contract suite for the FEAT-537 broadcast registry (TASK-2952).

Every test here runs against the ``registry`` fixture rather than a concrete
class, so TASK-2953 can re-point that fixture at ``RedisBroadcastRegistry`` and
prove the two implementations share one set of semantics.

Covers spec §2 "Ownership, admission and cleanup" and "Moderation and exclusive
speaking floor", plus AC2/AC3/AC12/AC13/AC14.
"""
from __future__ import annotations

import asyncio
from typing import Any, List

import pytest

from parrot.integrations.liveavatar.broadcast import (
    CONTROL_EXPIRY_S,
    MAX_VIEWERS,
    OWNER_LEASE_TTL_S,
    PENDING_TTL_S,
    BroadcastDescriptor,
    BroadcastReason,
    BroadcastState,
    ExpiryKind,
    FloorState,
    InMemoryBroadcastRegistry,
    LeaseState,
    ParticipantPrincipal,
    errors,
    validate_audio_authority,
)

TENANT = "acme"
AGENT = "agent-1"
BROADCAST = "bc-1"


class FakeClock:
    """Deterministic clock so TTL behaviour is testable without sleeping."""

    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        """Move the clock forward."""
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def registry(clock: FakeClock) -> InMemoryBroadcastRegistry:
    return InMemoryBroadcastRegistry(clock=clock)


def _principal(user: str = "user-1") -> ParticipantPrincipal:
    return ParticipantPrincipal(
        user_id=user, tenant_id=TENANT, agent_id=AGENT, display_name=user
    )


def _descriptor(**kwargs: Any) -> BroadcastDescriptor:
    defaults: dict[str, Any] = {
        "broadcast_id": BROADCAST,
        "tenant_id": TENANT,
        "agent_id": AGENT,
        "creator_user_id": "creator",
    }
    defaults.update(kwargs)
    return BroadcastDescriptor(**defaults)


async def _new_broadcast(
    registry: InMemoryBroadcastRegistry, **kwargs: Any
) -> BroadcastDescriptor:
    return await registry.create(_descriptor(**kwargs))


async def _join(
    registry: InMemoryBroadcastRegistry,
    user: str,
    *,
    confirm: bool = True,
    heartbeat: bool = True,
) -> Any:
    """Admit one participant and optionally confirm + heartbeat it."""
    admission = await registry.reserve_viewer(
        TENANT, BROADCAST, _principal(user), f"identity-{user}"
    )
    if confirm:
        await registry.confirm_viewer(TENANT, BROADCAST, admission.lease.lease_id)
    if heartbeat:
        await registry.heartbeat_control(TENANT, BROADCAST, admission.lease.lease_id)
    return admission


# ── Creation / lookup ──────────────────────────────────────────────────────


async def test_create_then_get(registry: InMemoryBroadcastRegistry) -> None:
    await _new_broadcast(registry)
    fetched = await registry.get(TENANT, BROADCAST)
    assert fetched is not None
    assert fetched.state is BroadcastState.PENDING
    assert fetched.moderator_lease_id is None


async def test_get_is_tenant_scoped(registry: InMemoryBroadcastRegistry) -> None:
    await _new_broadcast(registry)
    assert await registry.get("other-tenant", BROADCAST) is None
    assert await registry.get(TENANT, "other-broadcast") is None


async def test_duplicate_create_rejected(registry: InMemoryBroadcastRegistry) -> None:
    await _new_broadcast(registry)
    with pytest.raises(errors.BroadcastError):
        await _new_broadcast(registry)


async def test_get_returns_a_copy(registry: InMemoryBroadcastRegistry) -> None:
    await _new_broadcast(registry)
    first = await registry.get(TENANT, BROADCAST)
    assert first is not None
    first.state = BroadcastState.FAILED
    second = await registry.get(TENANT, BROADCAST)
    assert second is not None
    assert second.state is BroadcastState.PENDING


# ── Admission ──────────────────────────────────────────────────────────────


async def test_first_admission_elects_single_moderator_under_race(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    admissions = await asyncio.gather(
        *(
            registry.reserve_viewer(
                TENANT, BROADCAST, _principal(f"user-{index}"), f"identity-{index}"
            )
            for index in range(MAX_VIEWERS)
        )
    )
    assert len(admissions) == MAX_VIEWERS
    assert sum(1 for admission in admissions if admission.is_first) == 1

    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    first = next(a for a in admissions if a.is_first)
    assert first.lease.admission_sequence == 1
    assert descriptor.moderator_lease_id == first.lease.lease_id
    # The moderator also starts with the floor, at epoch 1.
    assert descriptor.speaker_lease_id == first.lease.lease_id
    assert descriptor.floor_state is FloorState.GRANTED
    assert descriptor.floor_epoch == 1

    sequences = sorted(a.lease.admission_sequence for a in admissions)
    assert sequences == list(range(1, MAX_VIEWERS + 1))
    lease_ids = {a.lease.lease_id for a in admissions}
    assert len(lease_ids) == MAX_VIEWERS


async def test_eleventh_viewer_rejected(registry: InMemoryBroadcastRegistry) -> None:
    await _new_broadcast(registry)
    for index in range(MAX_VIEWERS):
        await registry.reserve_viewer(
            TENANT, BROADCAST, _principal(f"user-{index}"), f"identity-{index}"
        )
    with pytest.raises(errors.ViewerLimitReached) as excinfo:
        await registry.reserve_viewer(
            TENANT, BROADCAST, _principal("user-11"), "identity-11"
        )
    assert excinfo.value.reason is BroadcastReason.VIEWER_LIMIT_REACHED
    assert excinfo.value.status == 409
    assert len(await registry.list_leases(TENANT, BROADCAST)) == MAX_VIEWERS


async def test_concurrent_eleventh_admission_never_over_admits(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    results = await asyncio.gather(
        *(
            registry.reserve_viewer(
                TENANT, BROADCAST, _principal(f"user-{index}"), f"identity-{index}"
            )
            for index in range(MAX_VIEWERS + 5)
        ),
        return_exceptions=True,
    )
    admitted = [r for r in results if not isinstance(r, BaseException)]
    rejected = [r for r in results if isinstance(r, errors.ViewerLimitReached)]
    assert len(admitted) == MAX_VIEWERS
    assert len(rejected) == 5


async def test_admission_on_terminal_broadcast_rejected(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    await registry.transition(
        TENANT, BROADCAST, BroadcastState.FAILED, expected_owner_epoch=0
    )
    with pytest.raises(errors.BroadcastTerminal) as excinfo:
        await registry.reserve_viewer(TENANT, BROADCAST, _principal(), "identity-x")
    assert excinfo.value.status == 410


async def test_tombstone_blocks_identity_reuse(
    registry: InMemoryBroadcastRegistry, clock: FakeClock
) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    joiner = await _join(registry, "guest")

    await registry.release_viewer(TENANT, BROADCAST, joiner.lease.lease_id)
    with pytest.raises(errors.IdentityTombstoned):
        await registry.reserve_viewer(
            TENANT, BROADCAST, _principal("guest"), "identity-guest"
        )

    # A fresh identity for the same user is fine straight away.
    await registry.reserve_viewer(
        TENANT, BROADCAST, _principal("guest"), "identity-guest-2"
    )

    # Once the tombstone lapses the original identity is reusable.
    clock.advance(120)
    await registry.expire(TENANT, BROADCAST)
    await registry.reserve_viewer(
        TENANT, BROADCAST, _principal("guest"), "identity-guest"
    )


async def test_tombstoned_seat_is_retained_against_over_admission(
    registry: InMemoryBroadcastRegistry, clock: FakeClock
) -> None:
    await _new_broadcast(registry)
    leases = [await _join(registry, f"user-{index}") for index in range(MAX_VIEWERS)]
    await registry.release_viewer(TENANT, BROADCAST, leases[-1].lease.lease_id)
    # The departed seat stays reserved until reuse cannot over-admit the room.
    with pytest.raises(errors.ViewerLimitReached):
        await registry.reserve_viewer(
            TENANT, BROADCAST, _principal("late"), "identity-late"
        )
    clock.advance(120)
    await registry.expire(TENANT, BROADCAST)
    await registry.reserve_viewer(TENANT, BROADCAST, _principal("late"), "identity-late")


async def test_confirm_and_heartbeat_do_not_bump_version(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    admission = await registry.reserve_viewer(
        TENANT, BROADCAST, _principal(), "identity-1"
    )
    await registry.confirm_viewer(TENANT, BROADCAST, admission.lease.lease_id)
    before = await registry.get(TENANT, BROADCAST)
    assert before is not None
    await registry.heartbeat_control(TENANT, BROADCAST, admission.lease.lease_id)
    after = await registry.get(TENANT, BROADCAST)
    assert after is not None
    assert after.version == before.version


async def test_list_leases_is_in_admission_order(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    for index in range(3):
        await _join(registry, f"user-{index}")
    leases = await registry.list_leases(TENANT, BROADCAST)
    assert [lease.admission_sequence for lease in leases] == [1, 2, 3]
    assert all(lease.state is LeaseState.ACTIVE for lease in leases)


# ── Ownership ──────────────────────────────────────────────────────────────


async def test_owner_claimed_once(registry: InMemoryBroadcastRegistry) -> None:
    await _new_broadcast(registry)
    claimed_a, epoch_a = await registry.claim_owner(TENANT, BROADCAST, "worker-a")
    claimed_b, epoch_b = await registry.claim_owner(TENANT, BROADCAST, "worker-b")
    assert claimed_a is True
    assert claimed_b is False
    assert epoch_a == epoch_b == 1


async def test_owner_lease_expires(
    registry: InMemoryBroadcastRegistry, clock: FakeClock
) -> None:
    await _new_broadcast(registry)
    _, epoch = await registry.claim_owner(TENANT, BROADCAST, "worker-a")
    assert await registry.renew_owner(TENANT, BROADCAST, "worker-a", epoch) is True

    clock.advance(OWNER_LEASE_TTL_S + 1)
    events = await registry.expire(TENANT, BROADCAST)
    assert any(event.kind is ExpiryKind.OWNER_LEASE for event in events)
    # The fenced owner can no longer renew.
    assert await registry.renew_owner(TENANT, BROADCAST, "worker-a", epoch) is False

    claimed, new_epoch = await registry.claim_owner(TENANT, BROADCAST, "worker-b")
    assert claimed is True
    assert new_epoch == epoch + 1


async def test_fenced_owner_cannot_transition(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    _, stale_epoch = await registry.claim_owner(TENANT, BROADCAST, "worker-a")
    # A second claim after expiry bumps the epoch, fencing the first owner.
    await registry.expire(TENANT, BROADCAST)
    with pytest.raises(errors.NotOwner):
        await registry.transition(
            TENANT,
            BROADCAST,
            BroadcastState.STARTING,
            expected_owner_epoch=stale_epoch + 5,
        )


# ── State machine ──────────────────────────────────────────────────────────


async def test_avatar_fallback_is_one_way(registry: InMemoryBroadcastRegistry) -> None:
    await _new_broadcast(registry)
    _, epoch = await registry.claim_owner(TENANT, BROADCAST, "worker-a")
    await registry.transition(
        TENANT, BROADCAST, BroadcastState.STARTING, expected_owner_epoch=epoch
    )
    await registry.transition(
        TENANT, BROADCAST, BroadcastState.AVATAR, expected_owner_epoch=epoch
    )
    await registry.transition(
        TENANT,
        BROADCAST,
        BroadcastState.AUDIO_ONLY,
        output_epoch=1,
        reason=BroadcastReason.AVATAR_CONTROL_LOST,
        expected_owner_epoch=epoch,
    )
    with pytest.raises(ValueError):
        await registry.transition(
            TENANT, BROADCAST, BroadcastState.AVATAR, expected_owner_epoch=epoch
        )


async def test_output_epoch_must_be_monotonic(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    _, epoch = await registry.claim_owner(TENANT, BROADCAST, "worker-a")
    await registry.transition(
        TENANT,
        BROADCAST,
        BroadcastState.STARTING,
        output_epoch=3,
        expected_owner_epoch=epoch,
    )
    with pytest.raises(ValueError):
        await registry.transition(
            TENANT,
            BROADCAST,
            BroadcastState.AVATAR,
            output_epoch=2,
            expected_owner_epoch=epoch,
        )


async def test_terminal_broadcast_cannot_transition(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    await registry.transition(
        TENANT, BROADCAST, BroadcastState.ENDED, expected_owner_epoch=0
    )
    with pytest.raises(errors.BroadcastTerminal):
        await registry.transition(
            TENANT, BROADCAST, BroadcastState.STARTING, expected_owner_epoch=0
        )


# ── Hands ──────────────────────────────────────────────────────────────────


async def test_raise_hand_is_idempotent_and_ordered(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    guest_a = await _join(registry, "guest-a")
    guest_b = await _join(registry, "guest-b")

    await registry.raise_hand(TENANT, BROADCAST, guest_a.lease.lease_id)
    await registry.raise_hand(TENANT, BROADCAST, guest_b.lease.lease_id)
    descriptor = await registry.raise_hand(TENANT, BROADCAST, guest_a.lease.lease_id)
    assert [hand.lease_id for hand in descriptor.hand_requests] == [
        guest_a.lease.lease_id,
        guest_b.lease.lease_id,
    ]
    assert [hand.sequence for hand in descriptor.hand_requests] == [1, 2]
    assert descriptor.hand_requests[0].display_name == "guest-a"


async def test_raising_a_hand_grants_no_permission(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    descriptor = await registry.raise_hand(TENANT, BROADCAST, guest.lease.lease_id)
    assert descriptor.speaker_lease_id == moderator.lease.lease_id
    with pytest.raises(errors.FloorNotGranted):
        validate_audio_authority(
            descriptor, guest.lease.lease_id, descriptor.floor_epoch, "socket-1"
        )


async def test_cancel_hand_is_idempotent(registry: InMemoryBroadcastRegistry) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    await registry.raise_hand(TENANT, BROADCAST, guest.lease.lease_id)
    await registry.cancel_hand(TENANT, BROADCAST, guest.lease.lease_id)
    descriptor = await registry.cancel_hand(TENANT, BROADCAST, guest.lease.lease_id)
    assert descriptor.hand_requests == []


async def test_only_moderator_dismisses_a_hand(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest_a = await _join(registry, "guest-a")
    guest_b = await _join(registry, "guest-b")
    await registry.raise_hand(TENANT, BROADCAST, guest_a.lease.lease_id)

    with pytest.raises(errors.NotModerator):
        await registry.dismiss_hand(
            TENANT, BROADCAST, guest_b.lease.lease_id, guest_a.lease.lease_id
        )
    descriptor = await registry.dismiss_hand(
        TENANT, BROADCAST, moderator.lease.lease_id, guest_a.lease.lease_id
    )
    assert descriptor.hand_requests == []
    # Dismissal changes no microphone permission.
    assert descriptor.speaker_lease_id == moderator.lease.lease_id


# ── Floor ──────────────────────────────────────────────────────────────────


async def test_grant_enters_switching_then_commit_grants(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None

    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    assert switching.floor_state is FloorState.SWITCHING
    assert switching.speaker_lease_id is None
    assert switching.floor_epoch == current.floor_epoch + 1

    granted = await registry.commit_floor(
        TENANT, BROADCAST, guest.lease.lease_id, switching.floor_epoch
    )
    assert granted.floor_state is FloorState.GRANTED
    assert granted.speaker_lease_id == guest.lease.lease_id


async def test_abort_leaves_the_floor_idle(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    idle = await registry.abort_floor(TENANT, BROADCAST, switching.floor_epoch)
    assert idle.floor_state is FloorState.IDLE
    assert idle.speaker_lease_id is None


async def test_conflicting_grants_install_one_speaker(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest_a = await _join(registry, "guest-a")
    guest_b = await _join(registry, "guest-b")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None

    results = await asyncio.gather(
        registry.grant_floor(
            TENANT,
            BROADCAST,
            moderator.lease.lease_id,
            guest_a.lease.lease_id,
            current.version,
        ),
        registry.grant_floor(
            TENANT,
            BROADCAST,
            moderator.lease.lease_id,
            guest_b.lease.lease_id,
            current.version,
        ),
        return_exceptions=True,
    )
    winners = [r for r in results if not isinstance(r, BaseException)]
    losers = [r for r in results if isinstance(r, errors.StaleVersion)]
    assert len(winners) == 1
    assert len(losers) == 1

    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.speaker_lease_id is None
    assert descriptor.floor_state is FloorState.SWITCHING


async def test_grant_while_switching_conflicts(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    with pytest.raises(errors.StaleVersion):
        await registry.grant_floor(
            TENANT,
            BROADCAST,
            moderator.lease.lease_id,
            moderator.lease.lease_id,
            switching.version,
        )


async def test_only_the_moderator_can_grant(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    with pytest.raises(errors.NotModerator):
        await registry.grant_floor(
            TENANT,
            BROADCAST,
            guest.lease.lease_id,
            guest.lease.lease_id,
            current.version,
        )


async def test_floor_cannot_be_granted_to_an_unadmitted_lease(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    with pytest.raises(errors.FloorNotGranted):
        await registry.grant_floor(
            TENANT, BROADCAST, moderator.lease.lease_id, "lease-ghost", current.version
        )


async def test_revoke_returns_the_floor_to_the_moderator(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    granted = await registry.commit_floor(
        TENANT, BROADCAST, guest.lease.lease_id, switching.floor_epoch
    )

    revoking = await registry.revoke_floor(
        TENANT, BROADCAST, moderator.lease.lease_id, granted.version
    )
    assert revoking.floor_state is FloorState.SWITCHING
    assert revoking.speaker_lease_id is None
    back = await registry.commit_floor(
        TENANT, BROADCAST, moderator.lease.lease_id, revoking.floor_epoch
    )
    assert back.speaker_lease_id == moderator.lease.lease_id


async def test_finish_speaking_returns_the_floor(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    await registry.commit_floor(
        TENANT, BROADCAST, guest.lease.lease_id, switching.floor_epoch
    )

    with pytest.raises(errors.NotSpeaker):
        await registry.release_floor(TENANT, BROADCAST, moderator.lease.lease_id)
    released = await registry.release_floor(
        TENANT, BROADCAST, guest.lease.lease_id
    )
    assert released.floor_state is FloorState.SWITCHING
    back = await registry.commit_floor(
        TENANT, BROADCAST, moderator.lease.lease_id, released.floor_epoch
    )
    assert back.speaker_lease_id == moderator.lease.lease_id


async def test_commit_with_a_stale_epoch_is_rejected(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    with pytest.raises(errors.StaleFloorEpoch):
        await registry.commit_floor(
            TENANT, BROADCAST, guest.lease.lease_id, switching.floor_epoch - 1
        )


async def test_commit_for_a_departed_target_leaves_the_floor_idle(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    await registry.release_viewer(TENANT, BROADCAST, guest.lease.lease_id)
    with pytest.raises(errors.FloorNotGranted):
        await registry.commit_floor(
            TENANT, BROADCAST, guest.lease.lease_id, switching.floor_epoch
        )
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.speaker_lease_id is None


# ── Audio authority ────────────────────────────────────────────────────────


async def test_stale_epoch_audio_rejected(registry: InMemoryBroadcastRegistry) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    stale_epoch = current.floor_epoch

    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    granted = await registry.commit_floor(
        TENANT, BROADCAST, guest.lease.lease_id, switching.floor_epoch
    )

    # The old speaker's in-flight audio is rejected on both counts.
    with pytest.raises(errors.FloorNotGranted):
        validate_audio_authority(
            granted, moderator.lease.lease_id, stale_epoch, "socket-old"
        )
    with pytest.raises(errors.StaleFloorEpoch):
        validate_audio_authority(
            granted, guest.lease.lease_id, stale_epoch, "socket-new"
        )
    # The new speaker at the current epoch is accepted.
    validate_audio_authority(
        granted, guest.lease.lease_id, granted.floor_epoch, "socket-new"
    )


async def test_no_audio_is_accepted_while_switching(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    for lease_id in (moderator.lease.lease_id, guest.lease.lease_id):
        with pytest.raises(errors.FloorNotGranted):
            validate_audio_authority(
                switching, lease_id, switching.floor_epoch, "socket-1"
            )


async def test_a_second_socket_cannot_take_over(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None

    assert (
        await registry.bind_speaker_socket(
            TENANT,
            BROADCAST,
            moderator.lease.lease_id,
            "socket-1",
            descriptor.floor_epoch,
        )
        is True
    )
    # Re-binding the same socket is idempotent.
    assert (
        await registry.bind_speaker_socket(
            TENANT,
            BROADCAST,
            moderator.lease.lease_id,
            "socket-1",
            descriptor.floor_epoch,
        )
        is True
    )
    with pytest.raises(errors.SpeakerConnectionExists) as excinfo:
        await registry.bind_speaker_socket(
            TENANT,
            BROADCAST,
            moderator.lease.lease_id,
            "socket-2",
            descriptor.floor_epoch,
        )
    assert excinfo.value.reason is BroadcastReason.SPEAKER_CONNECTION_EXISTS
    assert excinfo.value.status == 409

    validate_audio_authority(
        descriptor,
        moderator.lease.lease_id,
        descriptor.floor_epoch,
        "socket-1",
        bound_socket_id="socket-1",
    )
    with pytest.raises(errors.SpeakerConnectionExists):
        validate_audio_authority(
            descriptor,
            moderator.lease.lease_id,
            descriptor.floor_epoch,
            "socket-2",
            bound_socket_id="socket-1",
        )

    assert (
        await registry.unbind_speaker_socket(
            TENANT, BROADCAST, moderator.lease.lease_id, "socket-1"
        )
        is True
    )
    assert (
        await registry.unbind_speaker_socket(
            TENANT, BROADCAST, moderator.lease.lease_id, "socket-1"
        )
        is False
    )


async def test_a_grant_clears_the_previous_socket_binding(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    await registry.bind_speaker_socket(
        TENANT, BROADCAST, moderator.lease.lease_id, "socket-1", current.floor_epoch
    )
    await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    leases = {
        lease.lease_id: lease for lease in await registry.list_leases(TENANT, BROADCAST)
    }
    assert leases[moderator.lease.lease_id].speaker_socket_id is None


async def test_binding_requires_the_floor(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    with pytest.raises(errors.FloorNotGranted):
        await registry.bind_speaker_socket(
            TENANT, BROADCAST, guest.lease.lease_id, "socket-1", descriptor.floor_epoch
        )


# ── Departure, election, cleanup ───────────────────────────────────────────


async def test_speaker_departure_returns_the_floor_to_the_moderator(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    current = await registry.get(TENANT, BROADCAST)
    assert current is not None
    switching = await registry.grant_floor(
        TENANT,
        BROADCAST,
        moderator.lease.lease_id,
        guest.lease.lease_id,
        current.version,
    )
    await registry.commit_floor(
        TENANT, BROADCAST, guest.lease.lease_id, switching.floor_epoch
    )

    outcome = await registry.release_viewer(TENANT, BROADCAST, guest.lease.lease_id)
    assert outcome.audience_empty is False
    assert outcome.new_moderator is None
    assert outcome.floor_returned_to == moderator.lease.lease_id

    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.floor_state is FloorState.SWITCHING
    assert descriptor.speaker_lease_id is None
    assert descriptor.moderator_lease_id == moderator.lease.lease_id


async def test_moderator_departure_elects_earliest(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    second = await _join(registry, "second")
    third = await _join(registry, "third")

    outcome = await registry.release_viewer(TENANT, BROADCAST, moderator.lease.lease_id)
    assert outcome.audience_empty is False
    assert outcome.new_moderator == second.lease.lease_id
    assert outcome.floor_returned_to == second.lease.lease_id

    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.moderator_lease_id == second.lease.lease_id
    assert descriptor.speaker_lease_id is None
    assert descriptor.floor_state is FloorState.SWITCHING
    assert third.lease.lease_id != descriptor.moderator_lease_id


async def test_election_skips_unconfirmed_and_stale_participants(
    registry: InMemoryBroadcastRegistry, clock: FakeClock
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    stale = await _join(registry, "stale")
    unconfirmed = await _join(registry, "unconfirmed", confirm=False, heartbeat=False)
    clock.advance(CONTROL_EXPIRY_S + 1)
    healthy = await _join(registry, "healthy")

    outcome = await registry.release_viewer(TENANT, BROADCAST, moderator.lease.lease_id)
    assert outcome.new_moderator == healthy.lease.lease_id
    assert outcome.new_moderator not in (
        stale.lease.lease_id,
        unconfirmed.lease.lease_id,
    )


async def test_a_departing_participant_loses_its_hand_request(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    await registry.raise_hand(TENANT, BROADCAST, guest.lease.lease_id)
    await registry.release_viewer(TENANT, BROADCAST, guest.lease.lease_id)
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.hand_requests == []


async def test_last_departure_ends_the_broadcast(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    only = await _join(registry, "only")
    outcome = await registry.release_viewer(TENANT, BROADCAST, only.lease.lease_id)
    assert outcome.audience_empty is True
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.state is BroadcastState.ENDED
    assert descriptor.failure_reason is BroadcastReason.AUDIENCE_EMPTY


async def test_release_is_idempotent(registry: InMemoryBroadcastRegistry) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    await registry.release_viewer(TENANT, BROADCAST, guest.lease.lease_id)
    outcome = await registry.release_viewer(TENANT, BROADCAST, guest.lease.lease_id)
    assert outcome.audience_empty is False
    assert outcome.new_moderator is None


async def test_a_viewer_leaving_does_not_end_the_broadcast(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    viewer = await _join(registry, "viewer")
    await registry.release_viewer(TENANT, BROADCAST, viewer.lease.lease_id)
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.state is BroadcastState.PENDING
    assert descriptor.is_terminal is False


# ── Stop ───────────────────────────────────────────────────────────────────


async def test_only_the_moderator_can_stop(
    registry: InMemoryBroadcastRegistry,
) -> None:
    await _new_broadcast(registry)
    moderator = await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    assert await registry.stop_requested(TENANT, BROADCAST) is False
    with pytest.raises(errors.NotModerator):
        await registry.request_stop(TENANT, BROADCAST, guest.lease.lease_id)
    await registry.request_stop(TENANT, BROADCAST, moderator.lease.lease_id)
    # Idempotent.
    await registry.request_stop(TENANT, BROADCAST, moderator.lease.lease_id)
    assert await registry.stop_requested(TENANT, BROADCAST) is True


async def test_stop_requested_is_true_for_an_unknown_broadcast(
    registry: InMemoryBroadcastRegistry,
) -> None:
    # Fail closed: an owner whose record vanished must stop publishing.
    assert await registry.stop_requested(TENANT, "gone") is True


# ── Expiry / reconciliation ────────────────────────────────────────────────


async def test_pending_broadcast_expires(
    registry: InMemoryBroadcastRegistry, clock: FakeClock
) -> None:
    await _new_broadcast(registry)
    clock.advance(PENDING_TTL_S - 1)
    assert await registry.expire(TENANT, BROADCAST) == []
    clock.advance(2)
    events = await registry.expire(TENANT, BROADCAST)
    assert any(event.kind is ExpiryKind.PENDING_BROADCAST for event in events)
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.state is BroadcastState.ENDED
    assert descriptor.failure_reason is BroadcastReason.PENDING_EXPIRED


async def test_a_joined_broadcast_does_not_expire_as_pending(
    registry: InMemoryBroadcastRegistry, clock: FakeClock
) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    clock.advance(PENDING_TTL_S + 10)
    events = await registry.expire(TENANT, BROADCAST)
    assert not any(event.kind is ExpiryKind.PENDING_BROADCAST for event in events)
    descriptor = await registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    assert descriptor.is_terminal is False


async def test_stale_control_marks_leaving_but_keeps_the_seat(
    registry: InMemoryBroadcastRegistry, clock: FakeClock
) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    guest = await _join(registry, "guest")
    clock.advance(CONTROL_EXPIRY_S + 1)
    events = await registry.expire(TENANT, BROADCAST)
    kinds = {event.kind for event in events}
    assert ExpiryKind.CONTROL_HEARTBEAT in kinds

    leases = {
        lease.lease_id: lease for lease in await registry.list_leases(TENANT, BROADCAST)
    }
    # Fail closed: still holding its seat until the caller removes it from the
    # room and calls release_viewer.
    assert guest.lease.lease_id in leases
    assert leases[guest.lease.lease_id].state is LeaseState.LEAVING


async def test_unconfirmed_seat_past_its_deadline_is_reported(
    registry: InMemoryBroadcastRegistry, clock: FakeClock
) -> None:
    await _new_broadcast(registry)
    await _join(registry, "moderator")
    pending = await _join(registry, "pending", confirm=False, heartbeat=False)
    clock.advance(120)
    events = await registry.expire(TENANT, BROADCAST)
    matching = [
        event
        for event in events
        if event.kind is ExpiryKind.ADMISSION_DEADLINE
        and event.lease_id == pending.lease.lease_id
    ]
    assert matching


async def test_terminal_state_is_retained_then_dropped(
    registry: InMemoryBroadcastRegistry, clock: FakeClock
) -> None:
    await _new_broadcast(registry)
    only = await _join(registry, "only")
    await registry.release_viewer(TENANT, BROADCAST, only.lease.lease_id)

    clock.advance(60)
    await registry.expire(TENANT, BROADCAST)
    assert await registry.get(TENANT, BROADCAST) is not None

    clock.advance(300)
    events = await registry.expire(TENANT, BROADCAST)
    assert any(event.kind is ExpiryKind.TERMINAL_RETENTION for event in events)
    assert await registry.get(TENANT, BROADCAST) is None


async def test_expire_on_unknown_broadcast_is_a_noop(
    registry: InMemoryBroadcastRegistry,
) -> None:
    events: List[Any] = await registry.expire(TENANT, "gone")
    assert events == []
