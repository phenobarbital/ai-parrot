"""BroadcastService and reconciliation-watchdog tests (FEAT-537 TASK-2961).

Covers spec §2 "Ownership, admission and cleanup": exactly one producer per
broadcast under a race, idempotent admission credentials, moderator-only stop,
and a watchdog that fences a dead owner, evicts its room and reports what it
could **not** confirm rather than assuming it.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import pytest

from parrot.integrations.liveavatar.broadcast import (
    MAX_VIEWERS,
    BroadcastReason,
    BroadcastState,
    InMemoryBroadcastRegistry,
    ParticipantPrincipal,
    errors,
)
from parrot.integrations.liveavatar.broadcast.service import (
    BroadcastNotReady,
    BroadcastService,
    default_principal_resolver,
)

TENANT = "default"
AGENT = "agent-1"


class FakeClock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeUser:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.username = user_id
        self.roles: List[str] = []


class FakeRoomManager:
    """LiveKit stand-in that records every admin call."""

    def __init__(self) -> None:
        self.url = "wss://fake.livekit.cloud"
        self.calls: List[Tuple[str, Any]] = []
        self.participants: List[str] = []
        self.fail_list = False

    async def create_room(self, room: str, *, max_participants: int = 12) -> None:
        self.calls.append(("create_room", room))

    def mint_publisher_token(self, room: str, identity: str, **_kw: Any) -> str:
        return f"pub-{identity}"

    def mint_viewer_token(self, room: str, identity: str, *, ttl_s: int = 60) -> str:
        self.calls.append(("mint_viewer_token", (room, identity, ttl_s)))
        return f"viewer-{identity}"

    async def list_participant_identities(self, room: str) -> List[str]:
        self.calls.append(("list_participants", room))
        if self.fail_list:
            raise RuntimeError("livekit unreachable")
        return list(self.participants)

    async def remove_participant(self, room: str, identity: str) -> None:
        self.calls.append(("remove_participant", identity))

    async def delete_room(self, room: str) -> None:
        self.calls.append(("delete_room", room))

    def names(self) -> List[str]:
        return [name for name, _ in self.calls]


class FakeMediaSession:
    """Stands in for ``BroadcastSession``; records start/close and epochs."""

    instances: List["FakeMediaSession"] = []

    def __init__(
        self, descriptor: Any, registry: Any, room_manager: Any, worker_id: str, owner_epoch: int, **_kwargs: Any
    ) -> None:
        self.descriptor = descriptor
        self.registry = registry
        self.room_manager = room_manager
        self.worker_id = worker_id
        self.owner_epoch = owner_epoch
        self.output_epoch = 0
        self.floor_epoch = descriptor.floor_epoch
        self.room_name = descriptor.room_name or f"bcast-{descriptor.broadcast_id}"
        self.avatar_identity = "avatar-x"
        self.direct_identity = "direct-x"
        self.state = BroadcastState.PENDING
        self.started = 0
        self.closed_with: List[Tuple[Any, Any]] = []
        self.switches: List[Tuple[str, int]] = []
        FakeMediaSession.instances.append(self)

    async def start(self) -> BroadcastState:
        self.started += 1
        await self.registry.transition(
            self.descriptor.tenant_id,
            self.descriptor.broadcast_id,
            BroadcastState.STARTING,
            expected_owner_epoch=self.owner_epoch,
        )
        await self.registry.transition(
            self.descriptor.tenant_id,
            self.descriptor.broadcast_id,
            BroadcastState.AVATAR,
            output_epoch=1,
            expected_owner_epoch=self.owner_epoch,
        )
        self.state = BroadcastState.AVATAR
        return self.state

    def media_state(self) -> Dict[str, Any]:
        return {
            "room_name": self.room_name,
            "avatar_identity": self.avatar_identity,
            "direct_identity": self.direct_identity,
            "state": self.state.value,
            "output_epoch": self.output_epoch,
            "floor_epoch": self.floor_epoch,
            "reason": None,
            "liveavatar_session_id": "vendor-1",
        }

    async def switch_speaker(self, lease_id: str, floor_epoch: int) -> None:
        self.switches.append((lease_id, floor_epoch))
        self.floor_epoch = floor_epoch

    async def aclose(self, *, final_state: Any = None, reason: Any = None) -> None:
        self.closed_with.append((final_state, reason))


class FakeVoiceSession:
    """Stands in for ``BroadcastVoiceSession``."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.fanout: Any = None
        self.closed = 0
        self.turns: List[Tuple[str, str, int]] = []

    def set_fanout(self, fanout: Any) -> None:
        self.fanout = fanout

    def begin_speaker_turn(self, lease_id: str, principal: Any, floor_epoch: int) -> int:
        self.turns.append((lease_id, principal.user_id, floor_epoch))
        return len(self.turns)

    def end_speaker_turn(self) -> None:
        return None

    async def start_turn(self) -> None:
        return None

    async def push_audio(self, pcm: bytes) -> None:
        return None

    async def end_turn(self) -> None:
        return None

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture(autouse=True)
def _reset_sessions() -> None:
    FakeMediaSession.instances.clear()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def room_manager() -> FakeRoomManager:
    return FakeRoomManager()


@pytest.fixture
def service(clock: FakeClock, room_manager: FakeRoomManager) -> BroadcastService:
    registry = InMemoryBroadcastRegistry(clock=clock)
    return BroadcastService(
        registry,
        room_manager,  # type: ignore[arg-type]
        nova_bot_factory=lambda: None,
        worker_id="worker-a",
        clock=clock,
        session_factory=FakeMediaSession,
        voice_session_factory=FakeVoiceSession,
    )


async def _principal(service: BroadcastService, user: str) -> ParticipantPrincipal:
    return await service.resolve_principal(FakeUser(user), AGENT)


async def _create(service: BroadcastService, user: str = "creator") -> Tuple[Any, str]:
    principal = await _principal(service, user)
    descriptor = await service.create_broadcast(principal, AGENT)
    return principal, descriptor.broadcast_id


# ── Principals and scope ───────────────────────────────────────────────────


def test_default_principal_resolver_takes_tenant_from_configuration() -> None:
    """A client-chosen tenant would defeat the whole scoping model."""
    principal = default_principal_resolver(FakeUser("ada"), AGENT)
    assert principal.tenant_id == "default"
    assert principal.user_id == "ada"
    with pytest.raises(errors.BroadcastError):
        default_principal_resolver(None, AGENT)


async def test_authorization_is_more_than_authentication(clock: FakeClock, room_manager: FakeRoomManager) -> None:
    service = BroadcastService(
        InMemoryBroadcastRegistry(clock=clock),
        room_manager,  # type: ignore[arg-type]
        worker_id="worker-a",
        authorize_agent=lambda principal, agent: principal.user_id == "allowed",
    )
    await service.resolve_principal(FakeUser("allowed"), AGENT)
    with pytest.raises(errors.BroadcastError, match="not authorized"):
        await service.resolve_principal(FakeUser("denied"), AGENT)


async def test_out_of_scope_broadcast_is_indistinguishable_from_missing(
    service: BroadcastService,
) -> None:
    principal, broadcast_id = await _create(service)
    other = ParticipantPrincipal(user_id="x", tenant_id=TENANT, agent_id="another-agent")
    with pytest.raises(errors.BroadcastTerminal):
        await service.get_public_state(other, "another-agent", broadcast_id)


async def test_creation_confers_no_moderator_authority(
    service: BroadcastService,
) -> None:
    principal, broadcast_id = await _create(service, "creator")
    state = await service.get_public_state(principal, AGENT, broadcast_id)
    assert state.moderator_display_id is None
    # The creator only becomes moderator if they are also the first to join.
    other = await _principal(service, "first-joiner")
    admission = await service.join(other, AGENT, broadcast_id)
    assert admission.is_first is True
    state = await service.get_public_state(principal, AGENT, broadcast_id)
    assert state.moderator_display_id == admission.lease.lease_id


# ── Producer startup ───────────────────────────────────────────────────────


async def test_first_join_starts_producer_once_under_race(
    service: BroadcastService,
) -> None:
    _principal_obj, broadcast_id = await _create(service)
    principals = [await _principal(service, f"user-{i}") for i in range(MAX_VIEWERS)]

    admissions = await asyncio.gather(*(service.join(p, AGENT, broadcast_id) for p in principals))
    assert sum(1 for a in admissions if a.is_first) == 1
    assert len(FakeMediaSession.instances) == 1
    assert FakeMediaSession.instances[0].started == 1

    descriptor = await service.get_descriptor(TENANT, broadcast_id)
    assert descriptor is not None
    assert descriptor.owner_worker_id == "worker-a"
    assert descriptor.owner_epoch == 1


async def test_eleventh_join_is_refused(service: BroadcastService) -> None:
    _p, broadcast_id = await _create(service)
    for index in range(MAX_VIEWERS):
        await service.join(await _principal(service, f"u{index}"), AGENT, broadcast_id)
    with pytest.raises(errors.ViewerLimitReached):
        await service.join(await _principal(service, "late"), AGENT, broadcast_id)


async def test_a_worker_that_loses_the_owner_race_does_not_start_media(
    clock: FakeClock, room_manager: FakeRoomManager
) -> None:
    """Two producers would mean two conversations; spec forbids migration."""
    registry = InMemoryBroadcastRegistry(clock=clock)

    def _make(worker_id: str) -> BroadcastService:
        return BroadcastService(
            registry,
            room_manager,  # type: ignore[arg-type]
            nova_bot_factory=lambda: None,
            worker_id=worker_id,
            clock=clock,
            session_factory=FakeMediaSession,
            voice_session_factory=FakeVoiceSession,
        )

    first, second = _make("worker-a"), _make("worker-b")
    principal, broadcast_id = await _create(first)

    # worker-a wins ownership...
    await first.join(await _principal(first, "moderator"), AGENT, broadcast_id)
    assert len(FakeMediaSession.instances) == 1

    # ...and worker-b, serving a later participant, starts nothing.
    await second.join(await _principal(second, "guest"), AGENT, broadcast_id)
    assert len(FakeMediaSession.instances) == 1
    assert second.media_session(TENANT, broadcast_id) is None


# ── Admission credentials ──────────────────────────────────────────────────


async def test_connection_is_idempotent_per_lease(service: BroadcastService) -> None:
    _p, broadcast_id = await _create(service)
    principal = await _principal(service, "moderator")
    admission = await service.join(principal, AGENT, broadcast_id)

    first = await service.connection(principal, broadcast_id, admission.lease.lease_id)
    second = await service.connection(principal, broadcast_id, admission.lease.lease_id)
    assert first.client_token == second.client_token
    assert first.room == second.room
    assert first is second
    # Only one token was ever minted — a retry must not consume a fresh seat.
    room_manager: FakeRoomManager = service.room_manager  # type: ignore[assignment]
    assert room_manager.names().count("mint_viewer_token") == 1


async def test_connection_is_not_ready_while_starting(clock: FakeClock, room_manager: FakeRoomManager) -> None:
    """A browser polls; the server does not pretend credentials exist."""

    class _StalledSession(FakeMediaSession):
        async def start(self) -> BroadcastState:
            self.started += 1
            await self.registry.transition(
                self.descriptor.tenant_id,
                self.descriptor.broadcast_id,
                BroadcastState.STARTING,
                expected_owner_epoch=self.owner_epoch,
            )
            return BroadcastState.STARTING

    service = BroadcastService(
        InMemoryBroadcastRegistry(clock=clock),
        room_manager,  # type: ignore[arg-type]
        nova_bot_factory=lambda: None,
        worker_id="worker-a",
        clock=clock,
        session_factory=_StalledSession,
        voice_session_factory=FakeVoiceSession,
    )
    _p, broadcast_id = await _create(service)
    principal = await _principal(service, "moderator")
    admission = await service.join(principal, AGENT, broadcast_id)
    with pytest.raises(BroadcastNotReady) as excinfo:
        await service.connection(principal, broadcast_id, admission.lease.lease_id)
    assert excinfo.value.status == 409


async def test_connection_refuses_another_principals_lease(
    service: BroadcastService,
) -> None:
    _p, broadcast_id = await _create(service)
    owner = await _principal(service, "moderator")
    admission = await service.join(owner, AGENT, broadcast_id)
    intruder = await _principal(service, "intruder")
    await service.join(intruder, AGENT, broadcast_id)
    with pytest.raises(errors.BroadcastError, match="not owned"):
        await service.connection(intruder, broadcast_id, admission.lease.lease_id)


async def test_public_state_carries_producer_media_facts(
    service: BroadcastService,
) -> None:
    """The registry cannot store these, so the service joins them on."""
    _p, broadcast_id = await _create(service)
    principal = await _principal(service, "moderator")
    await service.join(principal, AGENT, broadcast_id)
    state = await service.get_public_state(principal, AGENT, broadcast_id)
    assert state.selected_identity == "avatar-x"
    assert state.media_ready is True
    dumped = state.model_dump(mode="json")
    for fragment in ("token", "secret", "ws_url", "api_key"):
        assert fragment not in str(dumped).lower()


# ── Floor and hands ────────────────────────────────────────────────────────


async def test_set_floor_runs_the_barrier_on_the_local_producer(
    service: BroadcastService,
) -> None:
    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    guest = await _principal(service, "guest")
    mod_admission = await service.join(moderator, AGENT, broadcast_id)
    guest_admission = await service.join(guest, AGENT, broadcast_id)
    await service.registry.confirm_viewer(TENANT, broadcast_id, guest_admission.lease.lease_id)

    descriptor = await service.get_descriptor(TENANT, broadcast_id)
    assert descriptor is not None
    result = await service.set_floor(moderator, broadcast_id, guest_admission.lease.lease_id, descriptor.version)
    assert result.descriptor.speaker_lease_id == guest_admission.lease.lease_id
    assert FakeMediaSession.instances[0].switches == [(guest_admission.lease.lease_id, result.floor_epoch)]
    assert result.previous_speaker_lease_id == mod_admission.lease.lease_id


async def test_only_the_moderator_can_set_the_floor(
    service: BroadcastService,
) -> None:
    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    guest = await _principal(service, "guest")
    await service.join(moderator, AGENT, broadcast_id)
    guest_admission = await service.join(guest, AGENT, broadcast_id)
    descriptor = await service.get_descriptor(TENANT, broadcast_id)
    assert descriptor is not None
    with pytest.raises(errors.NotModerator):
        await service.set_floor(guest, broadcast_id, guest_admission.lease.lease_id, descriptor.version)


async def test_raise_and_cancel_hand(service: BroadcastService) -> None:
    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    guest = await _principal(service, "guest")
    await service.join(moderator, AGENT, broadcast_id)
    admission = await service.join(guest, AGENT, broadcast_id)

    state = await service.raise_hand(guest, broadcast_id, admission.lease.lease_id)
    assert [h.lease_id for h in state.hand_requests] == [admission.lease.lease_id]
    # Raising a hand grants nothing.
    assert state.speaker_display_id != admission.lease.lease_id

    state = await service.cancel_hand(guest, broadcast_id, admission.lease.lease_id)
    assert state.hand_requests == []


async def test_a_participant_cannot_raise_another_hand(
    service: BroadcastService,
) -> None:
    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    guest = await _principal(service, "guest")
    mod_admission = await service.join(moderator, AGENT, broadcast_id)
    await service.join(guest, AGENT, broadcast_id)
    with pytest.raises(errors.BroadcastError, match="not owned"):
        await service.raise_hand(guest, broadcast_id, mod_admission.lease.lease_id)


# ── Stop and departure ─────────────────────────────────────────────────────


async def test_stop_requires_moderator(service: BroadcastService) -> None:
    _p, broadcast_id = await _create(service, "creator")
    moderator = await _principal(service, "moderator")
    guest = await _principal(service, "guest")
    await service.join(moderator, AGENT, broadcast_id)
    await service.join(guest, AGENT, broadcast_id)

    with pytest.raises(errors.NotModerator):
        await service.stop(guest, broadcast_id)
    # Even the creator is refused unless they are the moderator (spec §2).
    creator = await _principal(service, "creator")
    await service.join(creator, AGENT, broadcast_id)
    with pytest.raises(errors.NotModerator):
        await service.stop(creator, broadcast_id)

    await service.stop(moderator, broadcast_id)
    assert await service.registry.stop_requested(TENANT, broadcast_id) is True
    assert FakeMediaSession.instances[0].closed_with


async def test_leave_releases_the_seat_and_removes_the_participant(
    service: BroadcastService,
) -> None:
    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    guest = await _principal(service, "guest")
    await service.join(moderator, AGENT, broadcast_id)
    admission = await service.join(guest, AGENT, broadcast_id)

    await service.leave(guest, broadcast_id, admission.lease.lease_id)
    leases = await service.registry.list_leases(TENANT, broadcast_id)
    assert admission.lease.lease_id not in {lease.lease_id for lease in leases}
    room_manager: FakeRoomManager = service.room_manager  # type: ignore[assignment]
    assert "remove_participant" in room_manager.names()


async def test_last_departure_stops_the_producer(service: BroadcastService) -> None:
    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    admission = await service.join(moderator, AGENT, broadcast_id)
    await service.leave(moderator, broadcast_id, admission.lease.lease_id)

    assert service.media_session(TENANT, broadcast_id) is None
    assert FakeMediaSession.instances[0].closed_with[-1][1] is (BroadcastReason.AUDIENCE_EMPTY)


async def test_moderator_departure_elects_and_completes_the_barrier(
    service: BroadcastService,
) -> None:
    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    second = await _principal(service, "second")
    mod_admission = await service.join(moderator, AGENT, broadcast_id)
    second_admission = await service.join(second, AGENT, broadcast_id)
    await service.registry.confirm_viewer(TENANT, broadcast_id, second_admission.lease.lease_id)
    await service.registry.heartbeat_control(TENANT, broadcast_id, second_admission.lease.lease_id)

    await service.leave(moderator, broadcast_id, mod_admission.lease.lease_id)
    descriptor = await service.get_descriptor(TENANT, broadcast_id)
    assert descriptor is not None
    assert descriptor.moderator_lease_id == second_admission.lease.lease_id
    # The barrier the election opened was closed by the producer.
    assert descriptor.speaker_lease_id == second_admission.lease.lease_id


# ── Fan-out ────────────────────────────────────────────────────────────────


async def test_state_is_pushed_to_attached_control_sockets(
    service: BroadcastService,
) -> None:
    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    admission = await service.join(moderator, AGENT, broadcast_id)

    seen: List[Dict[str, Any]] = []

    async def _send(frame: Dict[str, Any]) -> None:
        seen.append(frame)

    await service.attach_control(TENANT, broadcast_id, admission.lease.lease_id, _send)
    await service.raise_hand(moderator, broadcast_id, admission.lease.lease_id)
    assert any(frame["type"] == "broadcast_state" for frame in seen)

    await service.detach_control(TENANT, broadcast_id, admission.lease.lease_id)
    before = len(seen)
    await service.cancel_hand(moderator, broadcast_id, admission.lease.lease_id)
    assert len(seen) == before


async def test_a_dead_socket_cannot_break_fan_out(service: BroadcastService) -> None:
    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    admission = await service.join(moderator, AGENT, broadcast_id)

    async def _boom(_frame: Dict[str, Any]) -> None:
        raise RuntimeError("socket gone")

    await service.attach_control(TENANT, broadcast_id, admission.lease.lease_id, _boom)
    await service.raise_hand(moderator, broadcast_id, admission.lease.lease_id)


# ── Speaker input routing ──────────────────────────────────────────────────


async def test_attach_speaker_input_is_local_when_this_worker_produces(
    service: BroadcastService,
) -> None:
    from parrot.integrations.liveavatar.broadcast.worker_transport import (
        LocalSpeakerInput,
    )

    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    admission = await service.join(moderator, AGENT, broadcast_id)
    sink = await service.attach_speaker_input(TENANT, broadcast_id, admission.lease.lease_id, moderator, 1)
    assert isinstance(sink, LocalSpeakerInput)
    await sink.start_turn()
    voice = service.voice_session(TENANT, broadcast_id)
    assert voice.turns == [(admission.lease.lease_id, "moderator", 1)]


async def test_attach_speaker_input_refuses_an_unreachable_producer(
    clock: FakeClock, room_manager: FakeRoomManager
) -> None:
    """No registered worker address means no relay — never a guessed URL."""
    registry = InMemoryBroadcastRegistry(clock=clock)
    owner = BroadcastService(
        registry,
        room_manager,
        nova_bot_factory=lambda: None,  # type: ignore[arg-type]
        worker_id="worker-a",
        clock=clock,
        session_factory=FakeMediaSession,
        voice_session_factory=FakeVoiceSession,
    )
    ingress = BroadcastService(
        registry,
        room_manager,
        worker_id="worker-b",
        clock=clock,  # type: ignore[arg-type]
        session_factory=FakeMediaSession,
        voice_session_factory=FakeVoiceSession,
    )
    _p, broadcast_id = await _create(owner)
    principal = await _principal(owner, "moderator")
    admission = await owner.join(principal, AGENT, broadcast_id)

    with pytest.raises(errors.BroadcastError, match="not reachable"):
        await ingress.attach_speaker_input(TENANT, broadcast_id, admission.lease.lease_id, principal, 1)


async def test_attach_speaker_input_relays_to_a_registered_worker(
    clock: FakeClock, room_manager: FakeRoomManager
) -> None:
    from parrot.integrations.liveavatar.broadcast.worker_transport import (
        RemoteSpeakerInput,
    )

    registry = InMemoryBroadcastRegistry(clock=clock)
    owner = BroadcastService(
        registry,
        room_manager,
        nova_bot_factory=lambda: None,  # type: ignore[arg-type]
        worker_id="worker-a",
        clock=clock,
        session_factory=FakeMediaSession,
        voice_session_factory=FakeVoiceSession,
    )
    ingress = BroadcastService(
        registry,
        room_manager,
        worker_id="worker-b",
        clock=clock,  # type: ignore[arg-type]
        session_factory=FakeMediaSession,
        voice_session_factory=FakeVoiceSession,
        worker_token="shared-secret",
    )
    await ingress.worker_registry.register("worker-a", "ws://127.0.0.1:9999")

    _p, broadcast_id = await _create(owner)
    principal = await _principal(owner, "moderator")
    admission = await owner.join(principal, AGENT, broadcast_id)

    sink = await ingress.attach_speaker_input(TENANT, broadcast_id, admission.lease.lease_id, principal, 1)
    assert isinstance(sink, RemoteSpeakerInput)
    await sink.aclose()


# ── Reconciliation watchdog ────────────────────────────────────────────────


async def test_reconciler_fences_dead_owner_and_cleans_room(clock: FakeClock, room_manager: FakeRoomManager) -> None:
    """Fence, evict every listed identity, delete the room, mark failed."""
    registry = InMemoryBroadcastRegistry(clock=clock)
    owner = BroadcastService(
        registry,
        room_manager,
        nova_bot_factory=lambda: None,  # type: ignore[arg-type]
        worker_id="worker-dead",
        clock=clock,
        session_factory=FakeMediaSession,
        voice_session_factory=FakeVoiceSession,
    )
    watchdog = BroadcastService(
        registry,
        room_manager,
        worker_id="worker-live",
        clock=clock,  # type: ignore[arg-type]
        session_factory=FakeMediaSession,
        voice_session_factory=FakeVoiceSession,
    )
    _p, broadcast_id = await _create(owner)
    principal = await _principal(owner, "moderator")
    await owner.join(principal, AGENT, broadcast_id)
    watchdog._known.add((TENANT, broadcast_id))  # noqa: SLF001
    room_manager.participants = ["viewer-1", "avatar-x", "direct-x"]

    # Nothing has expired yet.
    assert (await watchdog.reconcile_once()).fenced_owners == []

    # The owner goes silent past its 15 s lease.
    clock.advance(16.0)
    report = await watchdog.reconcile_once()

    assert report.fenced_owners == [broadcast_id]
    removed = {identity for _room, identity in report.removed_participants}
    assert removed == {"viewer-1", "avatar-x", "direct-x"}
    assert "delete_room" in room_manager.names()
    # Cannot confirm the vendor session stopped without the owner's token.
    assert report.orphaned_vendor_sessions == [broadcast_id]

    descriptor = await registry.get(TENANT, broadcast_id)
    assert descriptor is not None
    assert descriptor.state is BroadcastState.FAILED
    assert descriptor.failure_reason is BroadcastReason.OWNER_LOST
    # Well inside the 30 s cleanup target: one 5 s watchdog period after the
    # 15 s lease expiry.
    assert clock.t - 1_000.0 <= 30.0


async def test_reconciler_fails_closed_when_livekit_is_unreachable(
    clock: FakeClock, room_manager: FakeRoomManager
) -> None:
    registry = InMemoryBroadcastRegistry(clock=clock)
    owner = BroadcastService(
        registry,
        room_manager,
        nova_bot_factory=lambda: None,  # type: ignore[arg-type]
        worker_id="worker-dead",
        clock=clock,
        session_factory=FakeMediaSession,
        voice_session_factory=FakeVoiceSession,
    )
    watchdog = BroadcastService(
        registry,
        room_manager,
        worker_id="worker-live",
        clock=clock,  # type: ignore[arg-type]
        session_factory=FakeMediaSession,
        voice_session_factory=FakeVoiceSession,
    )
    _p, broadcast_id = await _create(owner)
    await owner.join(await _principal(owner, "moderator"), AGENT, broadcast_id)
    watchdog._known.add((TENANT, broadcast_id))  # noqa: SLF001
    room_manager.fail_list = True

    clock.advance(16.0)
    report = await watchdog.reconcile_once()
    assert broadcast_id in report.uncertain


async def test_reconciler_evicts_an_expired_control_lease_before_releasing_it(
    service: BroadcastService, clock: FakeClock, room_manager: FakeRoomManager
) -> None:
    """Room removal must precede the seat release, or a replacement overlaps."""
    _p, broadcast_id = await _create(service)
    moderator = await _principal(service, "moderator")
    guest = await _principal(service, "guest")
    await service.join(moderator, AGENT, broadcast_id)
    guest_admission = await service.join(guest, AGENT, broadcast_id)
    await service.registry.confirm_viewer(TENANT, broadcast_id, guest_admission.lease.lease_id)
    await service.registry.heartbeat_control(TENANT, broadcast_id, guest_admission.lease.lease_id)

    clock.advance(20.0)
    report = await service.reconcile_once()
    assert guest_admission.lease.lease_id in report.released_leases
    assert "remove_participant" in room_manager.names()
    leases = await service.registry.list_leases(TENANT, broadcast_id)
    assert guest_admission.lease.lease_id not in {lease.lease_id for lease in leases}


async def test_reconciler_survives_a_registry_outage(
    service: BroadcastService,
) -> None:
    _p, broadcast_id = await _create(service)

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("redis down")

    service.registry.expire = _boom  # type: ignore[method-assign]
    report = await service.reconcile_once()
    assert broadcast_id in report.uncertain


async def test_reconciler_task_lifecycle(service: BroadcastService) -> None:
    service._reconcile_interval_s = 0.01  # noqa: SLF001
    service.start_reconciler()
    service.start_reconciler()  # idempotent
    await asyncio.sleep(0.05)
    await service.aclose()
    assert service._reconciler is None  # noqa: SLF001


async def test_aclose_stops_every_local_producer(service: BroadcastService) -> None:
    _p, broadcast_id = await _create(service)
    await service.join(await _principal(service, "moderator"), AGENT, broadcast_id)
    await service.aclose()
    assert service.media_session(TENANT, broadcast_id) is None
    assert FakeMediaSession.instances[0].closed_with
