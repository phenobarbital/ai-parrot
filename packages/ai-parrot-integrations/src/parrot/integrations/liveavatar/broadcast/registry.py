"""Broadcast registry contract and in-memory reference implementation (FEAT-537).

Implements spec §2 "Ownership, admission and cleanup" and "Moderation and
exclusive speaking floor" as a **storage-agnostic** contract, plus the
in-memory implementation that defines the reference semantics
:class:`RedisBroadcastRegistry` (TASK-2953) must reproduce and that every
deterministic unit test runs against.

The registry owns *state and arbitration only*.  It never holds PCM, tokens,
AWS credentials, LiveAvatar access tokens or live SDK objects, and it never
talks to LiveKit — removing a participant from a room is the caller's job, and
the registry deliberately reports an expiry rather than releasing a seat behind
the caller's back (fail closed; see :meth:`BroadcastRegistry.expire`).

Three invariants hold at every await point:

* pending + active + tombstoned reservations never exceed ``max_viewers``;
* there is exactly one ``moderator_lease_id`` while any lease remains;
* there is at most one ``speaker_lease_id``, and it is ``None`` for the whole
  duration of a floor switch.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from parrot.integrations.liveavatar.broadcast.errors import (
    BroadcastError,
    BroadcastTerminal,
    FloorNotGranted,
    IdentityTombstoned,
    NotModerator,
    NotOwner,
    NotSpeaker,
    SpeakerConnectionExists,
    StaleFloorEpoch,
    StaleVersion,
    ViewerLimitReached,
)
from parrot.integrations.liveavatar.broadcast.models import (
    CONTROL_EXPIRY_S,
    OWNER_LEASE_TTL_S,
    PENDING_TTL_S,
    TERMINAL_RETENTION_S,
    VIEWER_CREDENTIAL_TTL_S,
    BroadcastDescriptor,
    BroadcastReason,
    BroadcastState,
    FloorState,
    HandRequest,
    LeaseState,
    ParticipantPrincipal,
    ViewerLease,
)

#: Legal non-terminal state edges.  ``avatar → audio_only`` is one-way: the
#: reverse edge is absent on purpose (fallback is sticky, spec §2).
_ALLOWED_TRANSITIONS: Dict[BroadcastState, frozenset[BroadcastState]] = {
    BroadcastState.PENDING: frozenset({BroadcastState.STARTING, BroadcastState.ENDED, BroadcastState.FAILED}),
    BroadcastState.STARTING: frozenset(
        {
            BroadcastState.AVATAR,
            BroadcastState.AUDIO_ONLY,
            BroadcastState.STOPPING,
            BroadcastState.ENDED,
            BroadcastState.FAILED,
        }
    ),
    BroadcastState.AVATAR: frozenset(
        {
            BroadcastState.AUDIO_ONLY,
            BroadcastState.STOPPING,
            BroadcastState.ENDED,
            BroadcastState.FAILED,
        }
    ),
    BroadcastState.AUDIO_ONLY: frozenset({BroadcastState.STOPPING, BroadcastState.ENDED, BroadcastState.FAILED}),
    BroadcastState.STOPPING: frozenset({BroadcastState.ENDED, BroadcastState.FAILED}),
    BroadcastState.ENDED: frozenset(),
    BroadcastState.FAILED: frozenset(),
}


def _utc(now: float) -> datetime:
    """Convert an epoch-seconds float from the injected clock to a UTC datetime.

    Args:
        now: Seconds since the Unix epoch, as produced by the registry clock.

    Returns:
        The equivalent timezone-aware UTC datetime.
    """
    return datetime.fromtimestamp(now, tz=timezone.utc)


# ── Result types ───────────────────────────────────────────────────────────


class Admission(NamedTuple):
    """Outcome of a seat reservation.

    Unpacks as the ``(lease, is_first)`` tuple the caller needs: ``is_first``
    is ``True`` for exactly one admission per broadcast — the one that elected
    the moderator — and tells the caller to run ``claim_owner`` plus producer
    startup **once**.

    Attributes:
        lease: The reserved :class:`ViewerLease`.
        is_first: Whether this admission elected the moderator.
    """

    lease: ViewerLease
    is_first: bool


@dataclass(frozen=True)
class ReleaseOutcome:
    """Consequences of releasing one viewer seat.

    Attributes:
        audience_empty: Whether no participants remain, so the caller must tear
            the producer down.
        floor_returned_to: Lease the floor barrier now targets, if the departure
            moved the floor.  The caller must acknowledge with ``commit_floor``.
        new_moderator: Lease elected as moderator, if the moderator departed.
    """

    audience_empty: bool
    floor_returned_to: Optional[str] = None
    new_moderator: Optional[str] = None


class ExpiryKind(str, Enum):
    """What a reconciliation pass found expired."""

    PENDING_BROADCAST = "pending_broadcast"
    OWNER_LEASE = "owner_lease"
    CONTROL_HEARTBEAT = "control_heartbeat"
    ADMISSION_DEADLINE = "admission_deadline"
    TERMINAL_RETENTION = "terminal_retention"
    TOMBSTONE = "tombstone"


@dataclass(frozen=True)
class ExpiryEvent:
    """One thing a reconciliation pass expired.

    Attributes:
        kind: What expired.
        lease_id: Lease concerned, for lease-scoped kinds.
        detail: Operator-facing detail; never returned to a client.
    """

    kind: ExpiryKind
    lease_id: Optional[str] = None
    detail: str = ""


# ── Stateless authority check ──────────────────────────────────────────────


def validate_audio_authority(
    descriptor: BroadcastDescriptor,
    lease_id: str,
    floor_epoch: int,
    socket_id: str,
    *,
    bound_socket_id: Optional[str] = None,
) -> None:
    """Reject microphone input that is unauthorized, stale or from a stray socket.

    Called at **both** ingress and the producer, immediately before queueing
    PCM (spec §2: "Validate authority at both ingress and the producer just
    before queueing PCM").  Pure and synchronous so the producer can call it
    per frame without touching the store.

    Socket possession, moderator role, or a valid LiveKit viewer JWT alone
    never authorize input — only the fencing tuple below does.

    Args:
        descriptor: Current broadcast descriptor.
        lease_id: Lease the frame claims to come from.
        floor_epoch: Floor epoch the frame was produced under.
        socket_id: Microphone socket the frame arrived on.
        bound_socket_id: The socket currently bound to the floor, when known.

    Raises:
        FloorNotGranted: If no floor is granted, or it is granted to someone
            else.
        StaleFloorEpoch: If the frame belongs to a superseded floor epoch.
        SpeakerConnectionExists: If a different socket holds the binding.
    """
    if descriptor.floor_state is not FloorState.GRANTED:
        raise FloorNotGranted(message="floor is not granted")
    if descriptor.speaker_lease_id != lease_id:
        raise FloorNotGranted(message="lease does not hold the floor")
    if descriptor.floor_epoch != floor_epoch:
        raise StaleFloorEpoch(message=f"floor epoch {floor_epoch} superseded by {descriptor.floor_epoch}")
    if bound_socket_id is not None and bound_socket_id != socket_id:
        raise SpeakerConnectionExists(message="another capture socket holds the floor")


# ── Contract ───────────────────────────────────────────────────────────────


class BroadcastRegistry(abc.ABC):
    """Storage-agnostic broadcast state, admission and moderation contract.

    Implementations must be safe to call concurrently from multiple tasks and,
    for the Redis implementation, from multiple worker processes.  Every
    mutating method takes an optional ``now`` so a distributed implementation
    can pass authoritative server time and tests can inject a fake clock.
    """

    # ── Lifecycle ──────────────────────────────────────────────────────

    @abc.abstractmethod
    async def create(self, descriptor: BroadcastDescriptor) -> BroadcastDescriptor:
        """Persist a new pending broadcast.

        Args:
            descriptor: Fully-formed pending descriptor.

        Returns:
            The stored descriptor.

        Raises:
            BroadcastError: If the broadcast id already exists.
        """

    @abc.abstractmethod
    async def get(self, tenant_id: str, broadcast_id: str) -> Optional[BroadcastDescriptor]:
        """Return a descriptor, or ``None`` when unknown or out of tenant scope."""

    @abc.abstractmethod
    async def transition(
        self,
        tenant_id: str,
        broadcast_id: str,
        new_state: BroadcastState,
        *,
        output_epoch: Optional[int] = None,
        reason: Optional[BroadcastReason] = None,
        expected_owner_epoch: int,
    ) -> BroadcastDescriptor:
        """Move the broadcast to ``new_state``, fenced by the ownership epoch.

        Args:
            tenant_id: Tenant scope.
            broadcast_id: Broadcast to transition.
            new_state: Target state.  ``audio_only → avatar`` is not legal.
            output_epoch: New monotonic output generation, when cutting over.
            reason: Sanitized reason to record.
            expected_owner_epoch: Ownership generation the caller believes it
                holds; a mismatch means it was fenced.

        Returns:
            The updated descriptor.

        Raises:
            NotOwner: If the caller's ownership epoch is stale.
            BroadcastTerminal: If the broadcast already ended or failed.
            ValueError: If the edge is not in the legal state graph.
        """

    # ── Ownership ──────────────────────────────────────────────────────

    @abc.abstractmethod
    async def claim_owner(
        self,
        tenant_id: str,
        broadcast_id: str,
        worker_id: str,
        *,
        now: Optional[float] = None,
    ) -> tuple[bool, int]:
        """Atomically claim producer ownership.

        Returns:
            ``(claimed, owner_epoch)``.  ``claimed`` is ``False`` when a live
            owner already holds the lease; ``owner_epoch`` is then that owner's
            epoch, so the caller can fence itself.
        """

    @abc.abstractmethod
    async def renew_owner(
        self,
        tenant_id: str,
        broadcast_id: str,
        worker_id: str,
        owner_epoch: int,
        *,
        now: Optional[float] = None,
    ) -> bool:
        """Extend an ownership lease.

        Returns:
            ``False`` when the caller has been fenced — it must stop publishing
            immediately rather than wait for its own lease to expire.
        """

    # ── Admission ──────────────────────────────────────────────────────

    @abc.abstractmethod
    async def reserve_viewer(
        self,
        tenant_id: str,
        broadcast_id: str,
        principal: ParticipantPrincipal,
        livekit_identity: str,
        *,
        now: Optional[float] = None,
    ) -> Admission:
        """Atomically reserve one of the ten receiving seats.

        The first successful reservation — and only the first — sets
        ``moderator_lease_id``, sets the initial ``speaker_lease_id`` to the
        same lease, moves the floor to ``granted`` at epoch 1, and reports
        ``is_first=True`` so the caller starts the producer exactly once.

        Raises:
            ViewerLimitReached: If seats plus retained reservations are full.
            IdentityTombstoned: If that LiveKit identity recently departed.
            BroadcastTerminal: If the broadcast ended or failed.
        """

    @abc.abstractmethod
    async def confirm_viewer(self, tenant_id: str, broadcast_id: str, lease_id: str) -> ViewerLease:
        """Mark a lease as an *active, confirmed* room participant."""

    @abc.abstractmethod
    async def heartbeat_control(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        *,
        now: Optional[float] = None,
    ) -> None:
        """Record a control-socket heartbeat.  Does **not** bump the version."""

    @abc.abstractmethod
    async def release_viewer(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        *,
        now: Optional[float] = None,
    ) -> ReleaseOutcome:
        """Release a seat idempotently and report the moderation consequences."""

    @abc.abstractmethod
    async def list_leases(self, tenant_id: str, broadcast_id: str) -> List[ViewerLease]:
        """Return every lease currently holding a seat, in admission order."""

    # ── Hands ──────────────────────────────────────────────────────────

    @abc.abstractmethod
    async def raise_hand(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        *,
        now: Optional[float] = None,
    ) -> BroadcastDescriptor:
        """Record an idempotent raise-hand request.  Grants no permission."""

    @abc.abstractmethod
    async def cancel_hand(self, tenant_id: str, broadcast_id: str, lease_id: str) -> BroadcastDescriptor:
        """Withdraw the caller's own hand request.  Idempotent."""

    @abc.abstractmethod
    async def dismiss_hand(
        self,
        tenant_id: str,
        broadcast_id: str,
        moderator_lease_id: str,
        target_lease_id: str,
    ) -> BroadcastDescriptor:
        """Moderator-only dismissal of another participant's request.

        Raises:
            NotModerator: If the caller is not the current moderator.
        """

    # ── Floor ──────────────────────────────────────────────────────────

    @abc.abstractmethod
    async def grant_floor(
        self,
        tenant_id: str,
        broadcast_id: str,
        moderator_lease_id: str,
        target_lease_id: Optional[str],
        expected_version: int,
    ) -> BroadcastDescriptor:
        """Open the handoff barrier towards ``target_lease_id``.

        Clears the permitted speaker, increments ``floor_epoch`` and enters
        ``switching`` atomically.  ``target_lease_id=None`` means *revoke* —
        the floor returns to the moderator once the barrier is acknowledged.

        Raises:
            NotModerator: If the caller is not the current moderator.
            StaleVersion: On a compare-and-set conflict, including an
                already-switching floor.
            FloorNotGranted: If the target is not an active admitted lease.
        """

    @abc.abstractmethod
    async def commit_floor(
        self, tenant_id: str, broadcast_id: str, target_lease_id: str, floor_epoch: int
    ) -> BroadcastDescriptor:
        """Acknowledge the barrier and install the new speaker.

        Raises:
            StaleFloorEpoch: If the floor is not switching at ``floor_epoch``.
            FloorNotGranted: If the target is not the pending target or has
                since departed.
        """

    @abc.abstractmethod
    async def abort_floor(self, tenant_id: str, broadcast_id: str, floor_epoch: int) -> BroadcastDescriptor:
        """Abandon a failed or timed-out barrier, leaving the floor idle."""

    @abc.abstractmethod
    async def release_floor(self, tenant_id: str, broadcast_id: str, speaker_lease_id: str) -> BroadcastDescriptor:
        """Speaker-initiated "Finish Speaking" — barrier back to the moderator.

        Raises:
            NotSpeaker: If the caller does not currently hold the floor.
        """

    @abc.abstractmethod
    async def revoke_floor(
        self,
        tenant_id: str,
        broadcast_id: str,
        moderator_lease_id: str,
        expected_version: int,
    ) -> BroadcastDescriptor:
        """Moderator revoke — :meth:`grant_floor` with a ``None`` target."""

    @abc.abstractmethod
    async def elect_moderator(self, tenant_id: str, broadcast_id: str, *, now: Optional[float] = None) -> Optional[str]:
        """Elect the earliest remaining healthy participant as moderator.

        Returns:
            The elected lease id, or ``None`` when nobody is eligible.
        """

    # ── Speaker socket binding ─────────────────────────────────────────

    @abc.abstractmethod
    async def bind_speaker_socket(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        socket_id: str,
        floor_epoch: int,
    ) -> bool:
        """Bind the single microphone socket permitted to send audio.

        Raises:
            FloorNotGranted: If the lease does not hold the floor.
            StaleFloorEpoch: If the epoch is superseded.
            SpeakerConnectionExists: If a different socket is already bound.
        """

    @abc.abstractmethod
    async def unbind_speaker_socket(self, tenant_id: str, broadcast_id: str, lease_id: str, socket_id: str) -> bool:
        """Drop a microphone-socket binding.  Idempotent."""

    # ── Stop and reconciliation ────────────────────────────────────────

    @abc.abstractmethod
    async def request_stop(self, tenant_id: str, broadcast_id: str, by_lease_id: str) -> BroadcastDescriptor:
        """Record the durable desired terminal state.  Moderator only.

        Raises:
            NotModerator: If the caller is not the current moderator.
        """

    @abc.abstractmethod
    async def stop_requested(self, tenant_id: str, broadcast_id: str) -> bool:
        """Whether a stop has been requested.  Polled by the owner every second."""

    @abc.abstractmethod
    @abc.abstractmethod
    async def set_media_state(
        self,
        tenant_id: str,
        broadcast_id: str,
        *,
        room_name: Optional[str] = None,
        avatar_identity: Optional[str] = None,
        direct_identity: Optional[str] = None,
        liveavatar_session_id: Optional[str] = None,
    ) -> Optional[BroadcastDescriptor]:
        """Persist producer-owned media facts onto the durable descriptor.

        The publisher identities decide which track a browser plays. They were
        previously known only to the process running the producer, so any other
        worker projected ``selected_identity=None`` and its viewers could not
        tell which publisher to attach — the descriptor had the fields, nothing
        ever filled them in.

        Args:
            tenant_id: Tenant scope.
            broadcast_id: Broadcast concerned.
            room_name: LiveKit room backing the broadcast.
            avatar_identity: Avatar publisher identity.
            direct_identity: Direct audio publisher identity.
            liveavatar_session_id: Vendor session id, when one exists.

        Returns:
            The updated descriptor, or ``None`` when it is gone.
        """

    @abc.abstractmethod
    async def list_broadcasts(self) -> List[Tuple[str, str]]:
        """Every live broadcast in the store, as ``(tenant_id, broadcast_id)``.

        Reconciliation needs this to be **store-wide**, not process-local: the
        whole point of fencing a dead owner is that some *other* worker — one
        that may never have served this broadcast — notices it and takes over.
        A reconciler that only walks what its own process happened to serve
        cannot, by construction, recover a broadcast whose only worker died.

        Returns:
            Live broadcasts, in unspecified order.
        """

    @abc.abstractmethod
    async def expire(self, tenant_id: str, broadcast_id: str, *, now: Optional[float] = None) -> List[ExpiryEvent]:
        """Run one reconciliation pass and report what expired.

        Deliberately conservative: an expired control participant is marked
        ``leaving`` and reported, **not** released.  The caller must remove it
        from the LiveKit room first and then call :meth:`release_viewer`, so an
        unreachable participant can never be replaced by an over-admitted one.
        """


# ── In-memory reference implementation ─────────────────────────────────────


@dataclass
class _Record:
    """Everything the in-memory registry keeps for one broadcast."""

    descriptor: BroadcastDescriptor
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    leases: Dict[str, ViewerLease] = field(default_factory=dict)
    #: LiveKit identity → tombstone expiry (epoch seconds).
    tombstones: Dict[str, float] = field(default_factory=dict)
    #: Ownership lease expiry (epoch seconds), or ``None`` when unowned.
    owner_expires_at: Optional[float] = None
    #: Lease the in-flight barrier targets while ``floor_state`` is switching.
    pending_floor_target: Optional[str] = None
    #: Durable desired terminal state (spec §2: not merely a pub/sub message).
    stop_requested_by: Optional[str] = None
    #: Monotonic sequence for hand-request ordering.
    hand_sequence: int = 0
    #: When a terminal state was reached, for the 5-minute retention window.
    terminal_at: Optional[float] = None
    #: Registry-clock creation time, authoritative for the pending TTL.
    created_at: float = 0.0


class InMemoryBroadcastRegistry(BroadcastRegistry):
    """Single-process reference implementation of :class:`BroadcastRegistry`.

    Serialises every mutation of one broadcast behind a per-broadcast
    :class:`asyncio.Lock`, which is what makes the concurrent-admission and
    conflicting-grant races deterministic.  This is the semantics the Redis
    implementation reproduces with atomic scripts.

    Args:
        clock: Callable returning epoch seconds.  Injected so TTL behaviour is
            testable without sleeping.
    """

    def __init__(self, *, clock: Optional[Callable[[], float]] = None) -> None:
        self._clock: Callable[[], float] = clock or time.time
        self._records: Dict[tuple[str, str], _Record] = {}
        self._registry_lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    # ── Internal helpers ───────────────────────────────────────────────

    def _now(self, now: Optional[float]) -> float:
        """Resolve the effective timestamp for an operation."""
        return self._clock() if now is None else now

    def _record(self, tenant_id: str, broadcast_id: str) -> _Record:
        """Return the record, raising when it is unknown or out of scope.

        Raises:
            BroadcastTerminal: If no such broadcast exists in this tenant.
        """
        record = self._records.get((tenant_id, broadcast_id))
        if record is None:
            raise BroadcastTerminal(message="unknown broadcast")
        return record

    @staticmethod
    def _require_live(record: _Record) -> None:
        """Reject operations on an ended or failed broadcast.

        Raises:
            BroadcastTerminal: If the broadcast is terminal.
        """
        if record.descriptor.is_terminal:
            raise BroadcastTerminal(reason=record.descriptor.failure_reason)

    @staticmethod
    def _touch(record: _Record, now: float, *, bump_version: bool = True) -> None:
        """Stamp ``updated_at`` and optionally bump the public version.

        Lease heartbeats call this with ``bump_version=False`` so a heartbeat
        never invalidates a moderator's in-flight compare-and-set (spec §2).
        """
        record.descriptor.updated_at = _utc(now)
        if bump_version:
            record.descriptor.version += 1

    def _occupied(self, record: _Record, now: float) -> int:
        """Seats that cannot be handed out: live leases plus live tombstones."""
        live_tombstones = sum(1 for expiry in record.tombstones.values() if expiry > now)
        return len(record.leases) + live_tombstones

    def _require_moderator(self, record: _Record, lease_id: str) -> None:
        """Reject a caller that is not the current moderator.

        Raises:
            NotModerator: Always, unless ``lease_id`` is the moderator.
        """
        if record.descriptor.moderator_lease_id is None or record.descriptor.moderator_lease_id != lease_id:
            raise NotModerator(message="caller is not the current moderator")

    @staticmethod
    def _drop_hand(record: _Record, lease_id: str) -> bool:
        """Remove one lease's hand request.  Returns whether anything changed."""
        before = len(record.descriptor.hand_requests)
        record.descriptor.hand_requests = [
            hand for hand in record.descriptor.hand_requests if hand.lease_id != lease_id
        ]
        return len(record.descriptor.hand_requests) != before

    def _open_barrier(self, record: _Record, target_lease_id: Optional[str], now: float) -> None:
        """Enter ``switching``: clear the speaker and increment the floor epoch.

        This is the single place the barrier is opened, so grant, revoke,
        release, departure and election all fence identically.
        """
        descriptor = record.descriptor
        if descriptor.speaker_lease_id is not None:
            speaker = record.leases.get(descriptor.speaker_lease_id)
            if speaker is not None:
                speaker.speaker_socket_id = None
        descriptor.speaker_lease_id = None
        descriptor.floor_epoch += 1
        descriptor.floor_state = FloorState.SWITCHING
        record.pending_floor_target = target_lease_id
        if target_lease_id is not None:
            self._drop_hand(record, target_lease_id)
        self._touch(record, now)

    def _eligible_moderators(self, record: _Record, now: float) -> List[ViewerLease]:
        """Confirmed, active leases with a fresh control heartbeat, in order."""
        eligible = [
            lease
            for lease in record.leases.values()
            if lease.state is LeaseState.ACTIVE
            and lease.confirmed
            and lease.last_control_heartbeat is not None
            and (now - lease.last_control_heartbeat.timestamp()) <= CONTROL_EXPIRY_S
        ]
        return sorted(eligible, key=lambda lease: lease.admission_sequence)

    def _any_live_lease(self, record: _Record, now: float) -> bool:
        """Whether any seat is still held by a participant who may come back.

        A ``leaving`` lease does not count: it has already been scheduled for
        eviction, so a broadcast whose every remaining seat is ``leaving`` is
        genuinely empty.

        Args:
            record: The broadcast record.
            now: Current registry time.

        Returns:
            ``True`` when at least one non-departing lease remains.
        """
        return any(
            lease.state is not LeaseState.LEAVING for lease in record.leases.values()
        )

    def _elect_locked(self, record: _Record, now: float) -> Optional[str]:
        """Elect the earliest eligible participant and hand it the floor."""
        candidates = self._eligible_moderators(record, now)
        if not candidates:
            record.descriptor.moderator_lease_id = None
            return None
        elected = candidates[0]
        record.descriptor.moderator_lease_id = elected.lease_id
        self._drop_hand(record, elected.lease_id)
        self._open_barrier(record, elected.lease_id, now)
        self.logger.info(
            "broadcast %s: elected lease %s as moderator (sequence %d)",
            record.descriptor.broadcast_id,
            elected.lease_id,
            elected.admission_sequence,
        )
        return elected.lease_id

    def _end_locked(self, record: _Record, reason: BroadcastReason, now: float) -> None:
        """Force the broadcast to ``ended`` with a sanitized reason."""
        if record.descriptor.is_terminal:
            return
        record.descriptor.state = BroadcastState.ENDED
        record.descriptor.failure_reason = reason
        record.descriptor.ended_at = _utc(now)
        record.descriptor.floor_state = FloorState.IDLE
        record.descriptor.speaker_lease_id = None
        record.descriptor.moderator_lease_id = None
        record.pending_floor_target = None
        record.terminal_at = now
        self._touch(record, now)

    def _lease(self, record: _Record, lease_id: str) -> ViewerLease:
        """Return a lease, raising when it is unknown.

        Raises:
            FloorNotGranted: If the lease does not hold a seat.
        """
        lease = record.leases.get(lease_id)
        if lease is None:
            raise FloorNotGranted(message="unknown lease")
        return lease

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def create(self, descriptor: BroadcastDescriptor) -> BroadcastDescriptor:
        key = (descriptor.tenant_id, descriptor.broadcast_id)
        async with self._registry_lock:
            if key in self._records:
                raise BroadcastError(message="broadcast already exists")
            now = self._clock()
            stored = descriptor.model_copy(deep=True)
            # The registry is the authority on server time: stamp the record
            # from its own clock rather than trusting the caller's wall clock,
            # so the pending TTL is measured against the same clock that
            # expires it.
            stored.created_at = _utc(now)
            stored.updated_at = _utc(now)
            record = _Record(descriptor=stored, created_at=now)
            self._records[key] = record
            self.logger.info(
                "broadcast %s created for agent %s",
                descriptor.broadcast_id,
                descriptor.agent_id,
            )
            return record.descriptor.model_copy(deep=True)

    async def get(self, tenant_id: str, broadcast_id: str) -> Optional[BroadcastDescriptor]:
        record = self._records.get((tenant_id, broadcast_id))
        if record is None:
            return None
        async with record.lock:
            return record.descriptor.model_copy(deep=True)

    async def transition(
        self,
        tenant_id: str,
        broadcast_id: str,
        new_state: BroadcastState,
        *,
        output_epoch: Optional[int] = None,
        reason: Optional[BroadcastReason] = None,
        expected_owner_epoch: int,
    ) -> BroadcastDescriptor:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            now = self._now(None)
            descriptor = record.descriptor
            if descriptor.owner_epoch != expected_owner_epoch:
                raise NotOwner(message=(f"owner epoch {expected_owner_epoch} fenced by " f"{descriptor.owner_epoch}"))
            if descriptor.is_terminal:
                raise BroadcastTerminal(reason=descriptor.failure_reason)
            if new_state is not descriptor.state:
                allowed = _ALLOWED_TRANSITIONS[descriptor.state]
                if new_state not in allowed:
                    raise ValueError(f"illegal broadcast transition {descriptor.state.value} → " f"{new_state.value}")
            if output_epoch is not None:
                if output_epoch < descriptor.output_epoch:
                    raise ValueError("output_epoch must be monotonic")
                descriptor.output_epoch = output_epoch
            if reason is not None:
                descriptor.failure_reason = reason
            if new_state is BroadcastState.STARTING and descriptor.started_at is None:
                descriptor.started_at = _utc(now)
            descriptor.state = new_state
            if descriptor.is_terminal:
                descriptor.ended_at = _utc(now)
                descriptor.floor_state = FloorState.IDLE
                descriptor.speaker_lease_id = None
                record.pending_floor_target = None
                record.terminal_at = now
            self._touch(record, now)
            return descriptor.model_copy(deep=True)

    # ── Ownership ──────────────────────────────────────────────────────

    async def claim_owner(
        self,
        tenant_id: str,
        broadcast_id: str,
        worker_id: str,
        *,
        now: Optional[float] = None,
    ) -> tuple[bool, int]:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            stamp = self._now(now)
            self._require_live(record)
            descriptor = record.descriptor
            live = (
                descriptor.owner_worker_id is not None
                and record.owner_expires_at is not None
                and record.owner_expires_at > stamp
            )
            if live and descriptor.owner_worker_id != worker_id:
                return False, descriptor.owner_epoch
            if live and descriptor.owner_worker_id == worker_id:
                record.owner_expires_at = stamp + OWNER_LEASE_TTL_S
                return True, descriptor.owner_epoch
            descriptor.owner_worker_id = worker_id
            descriptor.owner_epoch += 1
            record.owner_expires_at = stamp + OWNER_LEASE_TTL_S
            self._touch(record, stamp)
            self.logger.info(
                "broadcast %s: worker %s claimed ownership at epoch %d",
                broadcast_id,
                worker_id,
                descriptor.owner_epoch,
            )
            return True, descriptor.owner_epoch

    async def renew_owner(
        self,
        tenant_id: str,
        broadcast_id: str,
        worker_id: str,
        owner_epoch: int,
        *,
        now: Optional[float] = None,
    ) -> bool:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            stamp = self._now(now)
            descriptor = record.descriptor
            if descriptor.owner_worker_id != worker_id:
                return False
            if descriptor.owner_epoch != owner_epoch:
                return False
            if record.owner_expires_at is None or record.owner_expires_at <= stamp:
                return False
            record.owner_expires_at = stamp + OWNER_LEASE_TTL_S
            return True

    # ── Admission ──────────────────────────────────────────────────────

    async def reserve_viewer(
        self,
        tenant_id: str,
        broadcast_id: str,
        principal: ParticipantPrincipal,
        livekit_identity: str,
        *,
        now: Optional[float] = None,
    ) -> Admission:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            stamp = self._now(now)
            self._require_live(record)
            descriptor = record.descriptor

            tombstone = record.tombstones.get(livekit_identity)
            if tombstone is not None and tombstone > stamp:
                raise IdentityTombstoned(message="livekit identity is tombstoned; obtain a fresh identity")

            if self._occupied(record, stamp) >= descriptor.max_viewers:
                raise ViewerLimitReached(message=f"all {descriptor.max_viewers} seats are reserved")

            descriptor.admission_sequence += 1
            lease = ViewerLease(
                lease_id=f"lease-{uuid.uuid4().hex[:16]}",
                principal=principal,
                livekit_identity=livekit_identity,
                state=LeaseState.PENDING,
                credential_expires_at=_utc(stamp + VIEWER_CREDENTIAL_TTL_S),
                admission_deadline=_utc(stamp + VIEWER_CREDENTIAL_TTL_S),
                confirmed=False,
                admission_sequence=descriptor.admission_sequence,
                last_control_heartbeat=None,
                speaker_socket_id=None,
            )
            record.leases[lease.lease_id] = lease

            is_first = descriptor.moderator_lease_id is None and len(record.leases) == 1
            if is_first:
                # Moderator is decided here and nowhere else — not by the
                # creator's identity, not by a client role selector.
                descriptor.moderator_lease_id = lease.lease_id
                descriptor.speaker_lease_id = lease.lease_id
                descriptor.floor_epoch = 1
                descriptor.floor_state = FloorState.GRANTED
                record.pending_floor_target = None
                self.logger.info(
                    "broadcast %s: lease %s admitted first — moderator elected",
                    broadcast_id,
                    lease.lease_id,
                )
            self._touch(record, stamp)
            return Admission(lease=lease.model_copy(deep=True), is_first=is_first)

    async def confirm_viewer(self, tenant_id: str, broadcast_id: str, lease_id: str) -> ViewerLease:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            now = self._now(None)
            lease = self._lease(record, lease_id)
            lease.state = LeaseState.ACTIVE
            lease.confirmed = True
            if lease.last_control_heartbeat is None:
                lease.last_control_heartbeat = _utc(now)
            if record.descriptor.moderator_lease_id is None and not record.descriptor.is_terminal:
                # The role can be vacant after a moderator left with nobody
                # eligible yet.  This newly-confirmed participant may be that
                # successor, so fill it here rather than waiting for another
                # departure to trigger an election.
                self._elect_locked(record, now)
            self._touch(record, now)
            return lease.model_copy(deep=True)

    async def heartbeat_control(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        *,
        now: Optional[float] = None,
    ) -> None:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            stamp = self._now(now)
            lease = self._lease(record, lease_id)
            lease.last_control_heartbeat = _utc(stamp)
            # Heartbeats never bump the public version (spec §2).
            self._touch(record, stamp, bump_version=False)

    async def release_viewer(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        *,
        now: Optional[float] = None,
    ) -> ReleaseOutcome:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            stamp = self._now(now)
            descriptor = record.descriptor
            lease = record.leases.pop(lease_id, None)
            if lease is None:
                # Idempotent: releasing an already-released lease is a no-op.
                return ReleaseOutcome(audience_empty=not record.leases)

            # Identity tombstone through token validity (spec §2).
            #
            # The floor is `now + VIEWER_CREDENTIAL_TTL_S`, not `now`: viewer
            # credentials are minted at connection() time, which can be long
            # after admission, so a token issued a moment before this departure
            # stays valid for a further full TTL. Tombstoning only until the
            # admission-time `credential_expires_at` let that identity be
            # re-admitted while a working token for it was still in a browser.
            expiry = (
                lease.credential_expires_at.timestamp()
                if lease.credential_expires_at is not None
                else stamp + VIEWER_CREDENTIAL_TTL_S
            )
            record.tombstones[lease.livekit_identity] = max(
                expiry, stamp + VIEWER_CREDENTIAL_TTL_S
            )

            self._drop_hand(record, lease_id)
            was_speaker = descriptor.speaker_lease_id == lease_id
            was_moderator = descriptor.moderator_lease_id == lease_id
            floor_returned_to: Optional[str] = None
            new_moderator: Optional[str] = None

            if not record.leases:
                self._end_locked(record, BroadcastReason.AUDIENCE_EMPTY, stamp)
                return ReleaseOutcome(audience_empty=True)

            if was_moderator:
                descriptor.moderator_lease_id = None
                new_moderator = self._elect_locked(record, stamp)
                floor_returned_to = new_moderator
                if new_moderator is None and not self._any_live_lease(record, stamp):
                    # Nobody healthy remains to hold authority — end rather
                    # than leave an unresponsive participant in control.
                    self._end_locked(record, BroadcastReason.AUDIENCE_EMPTY, stamp)
                    return ReleaseOutcome(audience_empty=True)
                if new_moderator is None:
                    # Participants remain, but none is eligible *yet* (a seat
                    # awaiting presence confirmation, say).  Spec §105 is
                    # explicit — "do not stop the broadcast while others
                    # remain" — so the role goes vacant and is filled by the
                    # next confirmation or heartbeat.  Ending here reported
                    # `audience_empty` to an audience that was still watching,
                    # which also made the reason code lie during triage.
                    self.logger.warning(
                        "broadcast %s: moderator left with no eligible successor "
                        "yet; role vacant, %d lease(s) still present",
                        broadcast_id,
                        len(record.leases),
                    )
            elif was_speaker:
                # Speaker departure returns the floor to the moderator.
                floor_returned_to = descriptor.moderator_lease_id
                self._open_barrier(record, floor_returned_to, stamp)
            else:
                self._touch(record, stamp)

            return ReleaseOutcome(
                audience_empty=False,
                floor_returned_to=floor_returned_to,
                new_moderator=new_moderator,
            )

    async def list_leases(self, tenant_id: str, broadcast_id: str) -> List[ViewerLease]:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            ordered: Sequence[ViewerLease] = sorted(record.leases.values(), key=lambda lease: lease.admission_sequence)
            return [lease.model_copy(deep=True) for lease in ordered]

    # ── Hands ──────────────────────────────────────────────────────────

    async def raise_hand(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        *,
        now: Optional[float] = None,
    ) -> BroadcastDescriptor:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            stamp = self._now(now)
            self._require_live(record)
            lease = self._lease(record, lease_id)
            existing = {hand.lease_id for hand in record.descriptor.hand_requests}
            if lease_id not in existing:
                record.hand_sequence += 1
                record.descriptor.hand_requests.append(
                    HandRequest(
                        lease_id=lease_id,
                        display_name=lease.principal.display_name,
                        sequence=record.hand_sequence,
                        requested_at=_utc(stamp),
                    )
                )
                self._touch(record, stamp)
            return record.descriptor.model_copy(deep=True)

    async def cancel_hand(self, tenant_id: str, broadcast_id: str, lease_id: str) -> BroadcastDescriptor:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            now = self._now(None)
            if self._drop_hand(record, lease_id):
                self._touch(record, now)
            return record.descriptor.model_copy(deep=True)

    async def dismiss_hand(
        self,
        tenant_id: str,
        broadcast_id: str,
        moderator_lease_id: str,
        target_lease_id: str,
    ) -> BroadcastDescriptor:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            now = self._now(None)
            self._require_moderator(record, moderator_lease_id)
            if self._drop_hand(record, target_lease_id):
                self._touch(record, now)
            return record.descriptor.model_copy(deep=True)

    # ── Floor ──────────────────────────────────────────────────────────

    async def grant_floor(
        self,
        tenant_id: str,
        broadcast_id: str,
        moderator_lease_id: str,
        target_lease_id: Optional[str],
        expected_version: int,
    ) -> BroadcastDescriptor:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            now = self._now(None)
            self._require_live(record)
            descriptor = record.descriptor
            self._require_moderator(record, moderator_lease_id)
            if descriptor.version != expected_version:
                raise StaleVersion(message=(f"expected version {expected_version}, current " f"{descriptor.version}"))
            if descriptor.floor_state is FloorState.SWITCHING:
                raise StaleVersion(message="a floor switch is already in flight")

            resolved = target_lease_id or moderator_lease_id
            target = record.leases.get(resolved)
            if target is None or target.state is not LeaseState.ACTIVE:
                raise FloorNotGranted(message="only an active admitted participant can hold the floor")
            self._open_barrier(record, resolved, now)
            return descriptor.model_copy(deep=True)

    async def commit_floor(
        self, tenant_id: str, broadcast_id: str, target_lease_id: str, floor_epoch: int
    ) -> BroadcastDescriptor:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            now = self._now(None)
            descriptor = record.descriptor
            if descriptor.floor_state is not FloorState.SWITCHING or descriptor.floor_epoch != floor_epoch:
                raise StaleFloorEpoch(
                    message=(
                        f"barrier for epoch {floor_epoch} is no longer in flight "
                        f"(state={descriptor.floor_state.value}, "
                        f"epoch={descriptor.floor_epoch})"
                    )
                )
            if record.pending_floor_target != target_lease_id:
                raise FloorNotGranted(message="target is not the pending floor target")
            if target_lease_id not in record.leases:
                descriptor.floor_state = FloorState.IDLE
                record.pending_floor_target = None
                self._touch(record, now)
                raise FloorNotGranted(message="target departed before the barrier closed")
            descriptor.speaker_lease_id = target_lease_id
            descriptor.floor_state = FloorState.GRANTED
            record.pending_floor_target = None
            self._touch(record, now)
            return descriptor.model_copy(deep=True)

    async def abort_floor(self, tenant_id: str, broadcast_id: str, floor_epoch: int) -> BroadcastDescriptor:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            now = self._now(None)
            descriptor = record.descriptor
            if descriptor.floor_state is not FloorState.SWITCHING or descriptor.floor_epoch != floor_epoch:
                raise StaleFloorEpoch(message=f"no barrier in flight for epoch {floor_epoch}")
            descriptor.floor_state = FloorState.IDLE
            descriptor.speaker_lease_id = None
            record.pending_floor_target = None
            self._touch(record, now)
            return descriptor.model_copy(deep=True)

    async def release_floor(self, tenant_id: str, broadcast_id: str, speaker_lease_id: str) -> BroadcastDescriptor:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            now = self._now(None)
            self._require_live(record)
            descriptor = record.descriptor
            if descriptor.speaker_lease_id != speaker_lease_id:
                raise NotSpeaker(message="caller does not hold the floor")
            self._open_barrier(record, descriptor.moderator_lease_id, now)
            return descriptor.model_copy(deep=True)

    async def revoke_floor(
        self,
        tenant_id: str,
        broadcast_id: str,
        moderator_lease_id: str,
        expected_version: int,
    ) -> BroadcastDescriptor:
        return await self.grant_floor(tenant_id, broadcast_id, moderator_lease_id, None, expected_version)

    async def elect_moderator(self, tenant_id: str, broadcast_id: str, *, now: Optional[float] = None) -> Optional[str]:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            stamp = self._now(now)
            self._require_live(record)
            return self._elect_locked(record, stamp)

    # ── Speaker socket binding ─────────────────────────────────────────

    async def bind_speaker_socket(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        socket_id: str,
        floor_epoch: int,
    ) -> bool:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            now = self._now(None)
            descriptor = record.descriptor
            validate_audio_authority(descriptor, lease_id, floor_epoch, socket_id)
            lease = self._lease(record, lease_id)
            if lease.speaker_socket_id is not None and (lease.speaker_socket_id != socket_id):
                raise SpeakerConnectionExists(message="a capture socket is already bound to this lease")
            already_bound = lease.speaker_socket_id == socket_id
            lease.speaker_socket_id = socket_id
            if not already_bound:
                self._touch(record, now, bump_version=False)
            return True

    async def unbind_speaker_socket(self, tenant_id: str, broadcast_id: str, lease_id: str, socket_id: str) -> bool:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            lease = record.leases.get(lease_id)
            if lease is None or lease.speaker_socket_id != socket_id:
                return False
            lease.speaker_socket_id = None
            return True

    # ── Stop and reconciliation ────────────────────────────────────────

    async def request_stop(self, tenant_id: str, broadcast_id: str, by_lease_id: str) -> BroadcastDescriptor:
        record = self._record(tenant_id, broadcast_id)
        async with record.lock:
            now = self._now(None)
            self._require_moderator(record, by_lease_id)
            if record.stop_requested_by is None:
                record.stop_requested_by = by_lease_id
                record.descriptor.failure_reason = BroadcastReason.STOPPED_BY_MODERATOR
                self._touch(record, now)
            return record.descriptor.model_copy(deep=True)

    async def stop_requested(self, tenant_id: str, broadcast_id: str) -> bool:
        record = self._records.get((tenant_id, broadcast_id))
        if record is None:
            return True
        async with record.lock:
            return record.stop_requested_by is not None

    async def set_media_state(
        self,
        tenant_id: str,
        broadcast_id: str,
        *,
        room_name: Optional[str] = None,
        avatar_identity: Optional[str] = None,
        direct_identity: Optional[str] = None,
        liveavatar_session_id: Optional[str] = None,
    ) -> Optional[BroadcastDescriptor]:
        record = self._records.get((tenant_id, broadcast_id))
        if record is None:
            return None
        async with record.lock:
            now = self._now(None)
            updates = {
                "room_name": room_name,
                "avatar_identity": avatar_identity,
                "direct_identity": direct_identity,
                "liveavatar_session_id": liveavatar_session_id,
            }
            changed = False
            for field, value in updates.items():
                # Only ever fill in; a None means "unchanged", so a worker
                # without the fact cannot erase one another worker published.
                if value is not None and getattr(record.descriptor, field, None) != value:
                    setattr(record.descriptor, field, value)
                    changed = True
            if changed:
                self._touch(record, now)
            return record.descriptor.model_copy(deep=True)

    async def list_broadcasts(self) -> List[Tuple[str, str]]:
        return list(self._records.keys())

    async def expire(self, tenant_id: str, broadcast_id: str, *, now: Optional[float] = None) -> List[ExpiryEvent]:
        record = self._records.get((tenant_id, broadcast_id))
        if record is None:
            return []
        async with record.lock:
            stamp = self._now(now)
            events: List[ExpiryEvent] = []
            descriptor = record.descriptor

            # Expired identity tombstones free their retained reservation.
            for identity, expiry in list(record.tombstones.items()):
                if expiry <= stamp:
                    del record.tombstones[identity]
                    events.append(ExpiryEvent(kind=ExpiryKind.TOMBSTONE, detail="identity reusable again"))

            if descriptor.is_terminal:
                if record.terminal_at is not None and (stamp - record.terminal_at) >= TERMINAL_RETENTION_S:
                    self._records.pop((tenant_id, broadcast_id), None)
                    events.append(
                        ExpiryEvent(
                            kind=ExpiryKind.TERMINAL_RETENTION,
                            detail="sanitized terminal state expired",
                        )
                    )
                return events

            # Pending broadcast that nobody ever joined.
            if (
                descriptor.state is BroadcastState.PENDING
                and not record.leases
                and (stamp - record.created_at) >= PENDING_TTL_S
            ):
                self._end_locked(record, BroadcastReason.PENDING_EXPIRED, stamp)
                events.append(
                    ExpiryEvent(
                        kind=ExpiryKind.PENDING_BROADCAST,
                        detail="no admission within the pending TTL",
                    )
                )
                return events

            # Fence a dead producer so another worker can claim ownership.
            if (
                descriptor.owner_worker_id is not None
                and record.owner_expires_at is not None
                and record.owner_expires_at <= stamp
            ):
                fenced = descriptor.owner_worker_id
                descriptor.owner_worker_id = None
                record.owner_expires_at = None
                descriptor.failure_reason = BroadcastReason.OWNER_LOST
                self._touch(record, stamp)
                events.append(
                    ExpiryEvent(
                        kind=ExpiryKind.OWNER_LEASE,
                        detail=f"fenced expired owner {fenced}",
                    )
                )

            # Unconfirmed seats past their admission deadline.
            #
            # A lease already marked ``leaving`` is re-reported on every pass
            # rather than skipped.  Marking is not releasing: the caller must
            # first remove the participant from the room, and that call can
            # fail transiently.  Reporting the work only once meant a single
            # LiveKit blip stranded the seat forever — it stayed `leaving`,
            # kept occupying one of the ten slots, and no later pass ever
            # retried it.  Re-emitting makes eviction idempotent and retried.
            for lease in list(record.leases.values()):
                if (
                    not lease.confirmed
                    and lease.admission_deadline is not None
                    and lease.admission_deadline.timestamp() <= stamp
                ):
                    lease.state = LeaseState.LEAVING
                    events.append(
                        ExpiryEvent(
                            kind=ExpiryKind.ADMISSION_DEADLINE,
                            lease_id=lease.lease_id,
                            detail="pending seat never confirmed",
                        )
                    )

            # Stale control connections.  Marked leaving, NOT released: the
            # caller must remove the participant from the room first.
            for lease in list(record.leases.values()):
                if not lease.confirmed:
                    continue
                last = lease.last_control_heartbeat
                if last is not None and (stamp - last.timestamp()) > CONTROL_EXPIRY_S:
                    # Re-reported while still `leaving` — see the note above:
                    # an unreleased seat must keep asking to be evicted.
                    lease.state = LeaseState.LEAVING
                    events.append(
                        ExpiryEvent(
                            kind=ExpiryKind.CONTROL_HEARTBEAT,
                            lease_id=lease.lease_id,
                            detail="control heartbeat expired; remove from room first",
                        )
                    )
            if events:
                self._touch(record, stamp)
            return events


__all__ = [
    "Admission",
    "BroadcastRegistry",
    "ExpiryEvent",
    "ExpiryKind",
    "InMemoryBroadcastRegistry",
    "ReleaseOutcome",
    "validate_audio_authority",
]
