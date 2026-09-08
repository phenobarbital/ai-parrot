"""Speaking-floor authority and the moderated handoff barrier (FEAT-537).

Implements spec §2 "Moderation and exclusive speaking floor" — the half of
Module 4 that decides *who is allowed to talk*, separately from the transport
that carries their audio.

The barrier is the point of the whole module.  A naive handoff sets
``speaker_lease_id = new`` and hopes the old browser stops; that leaves a
window where two microphones reach Nova.  Instead every transition runs:

1. ``grant_floor`` → ``switching``, speaker cleared, ``floor_epoch`` +1.  From
   this instant *nobody* may send audio and every old-epoch frame is rejected.
2. Tell the outgoing speaker's socket to stop capturing.
3. ``BroadcastSession.switch_speaker`` — the producer cancels the in-flight
   turn, clears the software queue, interrupts the avatar and purges the native
   audio queue, then **acknowledges**.
4. Only then ``commit_floor`` installs the new speaker.

If step 3 fails or times out, ``abort_floor`` leaves the floor **idle** and the
caller gets a retryable error.  Silence with a visible error is the correct
outcome; two live speakers is not (spec §2, AC13).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol, Union

from parrot.integrations.liveavatar.broadcast.errors import (
    BroadcastError,
    FloorNotGranted,
    StaleFloorEpoch,
)
from parrot.integrations.liveavatar.broadcast.models import (
    CONTROL_EXPIRY_S,
    BroadcastDescriptor,
    BroadcastReason,
    ViewerLease,
)
from parrot.integrations.liveavatar.broadcast.registry import (
    BroadcastRegistry,
    validate_audio_authority as _validate_fencing_tuple,
)

_logger = logging.getLogger(__name__)

#: Notification sent to a socket that just lost the floor.
FLOOR_REVOKED = "floor_revoked"

#: Notification carrying the caller's own microphone permission.
FLOOR_STATE = "floor_state"

Notifier = Callable[[str, Dict[str, Any]], Union[Awaitable[None], None]]


class BroadcastControlService(Protocol):
    """What the broadcast WebSocket route needs from the service layer.

    Declared here, as a ``Protocol``, so TASK-2960's transport can be written
    and tested against an explicit contract instead of prose, and so TASK-2961's
    concrete ``BroadcastService`` has a machine-checkable target.  The handler
    never imports the concrete class — that would drag the optional
    LiveKit/Redis stack into every voice deployment.
    """

    async def resolve_principal(self, user: Any, agent_id: str) -> Any:
        """Map an authenticated user plus an agent id to a scoped principal."""
        ...

    async def get_descriptor(self, tenant_id: str, broadcast_id: str) -> Any:
        """Return the current descriptor, or ``None``."""
        ...

    async def get_lease(self, tenant_id: str, broadcast_id: str, lease_id: str) -> Any:
        """Return one lease, or ``None``."""
        ...

    async def heartbeat(self, tenant_id: str, broadcast_id: str, lease_id: str) -> None:
        """Record a control-socket heartbeat for a lease."""
        ...

    async def attach_control(self, tenant_id: str, broadcast_id: str, lease_id: str, send: Notifier) -> None:
        """Register a control socket so state changes can be pushed to it."""
        ...

    async def detach_control(self, tenant_id: str, broadcast_id: str, lease_id: str) -> None:
        """Deregister a control socket."""
        ...

    async def public_state(self, tenant_id: str, broadcast_id: str) -> Dict[str, Any]:
        """Return the browser-safe projection of the broadcast."""
        ...

    async def bind_speaker_socket(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        socket_id: str,
        floor_epoch: int,
    ) -> bool:
        """Bind the one microphone socket allowed to send audio."""
        ...

    async def unbind_speaker_socket(self, tenant_id: str, broadcast_id: str, lease_id: str, socket_id: str) -> bool:
        """Release a microphone-socket binding."""
        ...

    def voice_session(self, tenant_id: str, broadcast_id: str) -> Any:
        """Return the broadcast-owned voice session on this worker, or ``None``."""
        ...

    def media_session(self, tenant_id: str, broadcast_id: str) -> Any:
        """Return the ``BroadcastSession`` on this worker, or ``None``."""
        ...

    async def release_floor(self, tenant_id: str, broadcast_id: str, speaker_lease_id: str) -> Any:
        """Run the Finish-Speaking barrier back to the moderator."""
        ...


def validate_audio_authority(
    descriptor: BroadcastDescriptor,
    lease: Optional[ViewerLease],
    *,
    floor_epoch: Optional[int],
    socket_id: str,
    now: Optional[float] = None,
) -> None:
    """Reject microphone input that is not authorized *right now*.

    Applied at ingress and again at the producer, immediately before any
    provider call.  Deliberately strict about what does **not** authorize
    input: possessing the socket, being the moderator, or holding a valid
    LiveKit viewer JWT are all insufficient (spec §2).

    The core fencing-tuple check (granted / right lease / right epoch / right
    socket) is **delegated** to
    :func:`~.registry.validate_audio_authority` so there is exactly one
    implementation of that rule.  This wrapper adds the two things the registry
    version cannot see because it takes only a lease *id*: the socket binding
    stored on the lease, and control-connection freshness.

    Args:
        descriptor: Current broadcast state.
        lease: The caller's lease, or ``None`` when it no longer exists.
        floor_epoch: Epoch the client claims to be sending under.  ``None``
            means the client omitted it, which is treated as stale rather than
            waved through — an old client must not bypass fencing by silence.
        socket_id: The socket the frame arrived on.
        now: Optional timestamp for the control-freshness check.

    Raises:
        FloorNotGranted: No floor is granted, the caller does not hold it, the
            lease has gone away, or its control connection is stale.
        StaleFloorEpoch: The epoch is missing or superseded.
        SpeakerConnectionExists: A different socket holds the binding.
    """
    if lease is None:
        raise FloorNotGranted(message="no admitted lease for this socket")
    if floor_epoch is None:
        # An omitted epoch is not "unfenced", it is stale.  Otherwise an old
        # client could bypass every handoff simply by not sending the field.
        raise StaleFloorEpoch(message="floor_epoch is required for audio input")

    _validate_fencing_tuple(
        descriptor,
        lease.lease_id,
        floor_epoch,
        socket_id,
        bound_socket_id=lease.speaker_socket_id,
    )

    if now is not None and lease.last_control_heartbeat is not None:
        age = now - lease.last_control_heartbeat.timestamp()
        if age > CONTROL_EXPIRY_S:
            # Uncertain control ownership: reject input rather than risk a
            # second moderator/speaker (spec §2).
            raise FloorNotGranted(message=f"control heartbeat is {age:.1f}s stale")


@dataclass
class HandoffResult:
    """Outcome of one completed floor transition.

    Attributes:
        descriptor: Broadcast state after ``commit_floor``.
        previous_speaker_lease_id: Who held the floor before, if anyone.
        floor_epoch: The epoch the new speaker was installed under.
    """

    descriptor: BroadcastDescriptor
    previous_speaker_lease_id: Optional[str]
    floor_epoch: int


class FloorCoordinator:
    """Sequences registry state, socket notifications and the producer barrier.

    Args:
        notifier: Called as ``notifier(lease_id, frame)`` to reach one
            participant's control socket.  Failures are swallowed — Redis
            remains authoritative and a browser that missed a notification
            recovers on its next poll (spec §2).
    """

    def __init__(
        self,
        notifier: Optional[Notifier] = None,
        remote_barrier: Optional[Callable[[str, str], Any]] = None,
    ) -> None:
        self._notifier = notifier
        self._remote_barrier = remote_barrier
        self.logger = logging.getLogger(__name__)

    def _barrier_for(
        self, session: Any, tenant_id: str, broadcast_id: str
    ) -> Optional[Callable[[str, int], Awaitable[None]]]:
        """Pick the producer barrier for a local or a remote producer.

        Args:
            session: The local :class:`BroadcastSession`, or ``None`` when the
                producer lives on another worker.
            tenant_id: Tenant scope, for binding a remote barrier.
            broadcast_id: Broadcast concerned.

        Returns:
            A coroutine ``(target_lease_id, floor_epoch) -> None``, or ``None``
            when there is no producer to fence at all.
        """
        if session is not None:

            async def _local(target_lease_id: str, floor_epoch: int) -> None:
                await session.switch_speaker(target_lease_id, floor_epoch)

            return _local
        if self._remote_barrier is None:
            return None
        return self._remote_barrier(tenant_id, broadcast_id)

    async def _notify(self, lease_id: Optional[str], frame: Dict[str, Any]) -> None:
        """Best-effort push to one participant's control socket."""
        if lease_id is None or self._notifier is None:
            return
        try:
            result = self._notifier(lease_id, frame)
            if hasattr(result, "__await__"):
                await result  # type: ignore[misc]
        except Exception:  # noqa: BLE001 — notifications are advisory
            self.logger.debug("floor coordinator: notify %s failed", lease_id, exc_info=True)

    async def handoff(
        self,
        registry: BroadcastRegistry,
        session: Any,
        *,
        tenant_id: str,
        broadcast_id: str,
        moderator_lease_id: str,
        target_lease_id: Optional[str],
        expected_version: int,
    ) -> HandoffResult:
        """Move the floor, with the producer barrier in the middle.

        Args:
            registry: Shared state store.
            session: The owning :class:`BroadcastSession`, or ``None`` when the
                producer lives on another worker (the caller then relays the
                barrier).
            tenant_id: Tenant scope.
            broadcast_id: Broadcast to transition.
            moderator_lease_id: The caller — must be the current moderator.
            target_lease_id: Lease to grant, or ``None`` to revoke (the floor
                returns to the moderator).
            expected_version: Compare-and-set guard against a concurrent grant.

        Returns:
            The completed :class:`HandoffResult`.

        Raises:
            NotModerator: If the caller is not the current moderator.
            StaleVersion: On a concurrent or already-switching conflict.
            BroadcastError: With ``stale_floor_epoch`` when the producer does
                not acknowledge; the floor is left idle and the error is
                retryable.
        """
        before = await registry.get(tenant_id, broadcast_id)
        previous_speaker = before.speaker_lease_id if before else None

        switching = await registry.grant_floor(
            tenant_id,
            broadcast_id,
            moderator_lease_id,
            target_lease_id,
            expected_version,
        )
        resolved_target = target_lease_id or moderator_lease_id
        return await self._run_barrier(
            registry,
            session,
            tenant_id=tenant_id,
            broadcast_id=broadcast_id,
            switching=switching,
            target_lease_id=resolved_target,
            previous_speaker=previous_speaker,
        )

    async def release(
        self,
        registry: BroadcastRegistry,
        session: Any,
        *,
        tenant_id: str,
        broadcast_id: str,
        speaker_lease_id: str,
    ) -> HandoffResult:
        """Finish Speaking / speaker departure — floor back to the moderator.

        Uses the *same* barrier as a moderator grant, so a speaker releasing
        the floor cannot leave a shorter window than a revoke would.

        Args:
            registry: Shared state store.
            session: The owning :class:`BroadcastSession`, or ``None``.
            tenant_id: Tenant scope.
            broadcast_id: Broadcast concerned.
            speaker_lease_id: The lease giving the floor up.

        Returns:
            The completed :class:`HandoffResult`.

        Raises:
            NotSpeaker: If the caller does not hold the floor.
            BroadcastError: On barrier failure.
        """
        switching = await registry.release_floor(tenant_id, broadcast_id, speaker_lease_id)
        target = switching.moderator_lease_id
        return await self._run_barrier(
            registry,
            session,
            tenant_id=tenant_id,
            broadcast_id=broadcast_id,
            switching=switching,
            target_lease_id=target,
            previous_speaker=speaker_lease_id,
        )

    async def succeed_moderator(
        self,
        registry: BroadcastRegistry,
        session: Any,
        *,
        tenant_id: str,
        broadcast_id: str,
        new_moderator_lease_id: str,
        floor_epoch: int,
        previous_speaker: Optional[str] = None,
    ) -> HandoffResult:
        """Complete the barrier a departure-driven election already opened.

        ``release_viewer`` / ``elect_moderator`` open the barrier inside the
        registry (atomically, so no second moderator can appear), leaving the
        producer acknowledgement to the owning worker — this method.

        Args:
            registry: Shared state store.
            session: The owning :class:`BroadcastSession`, or ``None``.
            tenant_id: Tenant scope.
            broadcast_id: Broadcast concerned.
            new_moderator_lease_id: The elected lease.
            floor_epoch: Epoch the election opened.
            previous_speaker: Lease to notify, if it is still connected.

        Returns:
            The completed :class:`HandoffResult`.

        Raises:
            BroadcastError: On barrier failure.
        """
        descriptor = await registry.get(tenant_id, broadcast_id)
        if descriptor is None:
            raise BroadcastError(message="broadcast disappeared during succession")
        return await self._run_barrier(
            registry,
            session,
            tenant_id=tenant_id,
            broadcast_id=broadcast_id,
            switching=descriptor,
            target_lease_id=new_moderator_lease_id,
            previous_speaker=previous_speaker,
            expected_epoch=floor_epoch,
        )

    async def _run_barrier(
        self,
        registry: BroadcastRegistry,
        session: Any,
        *,
        tenant_id: str,
        broadcast_id: str,
        switching: BroadcastDescriptor,
        target_lease_id: Optional[str],
        previous_speaker: Optional[str],
        expected_epoch: Optional[int] = None,
    ) -> HandoffResult:
        """Notify, ask the producer to fence, then install the new speaker.

        Ordering is load-bearing and is asserted by the tests: the registry is
        already in ``switching`` before this runs, so audio is refused for the
        whole duration regardless of how long the producer takes.
        """
        floor_epoch = expected_epoch or switching.floor_epoch

        # 2. Tell the outgoing browser to stop capturing.  Advisory only — the
        #    server has already stopped accepting its audio.
        if previous_speaker and previous_speaker != target_lease_id:
            await self._notify(
                previous_speaker,
                {
                    "type": FLOOR_REVOKED,
                    "floor_epoch": floor_epoch,
                    "reason": BroadcastReason.FLOOR_NOT_GRANTED.value,
                },
            )

        # 3. Producer barrier.  When the producer lives on another worker the
        #    barrier is relayed to it: skipping it there would commit a handoff
        #    the producer never fenced, so the outgoing speaker's in-flight
        #    audio could still surface under the incoming one.
        barrier = self._barrier_for(session, tenant_id, broadcast_id)
        if barrier is not None and target_lease_id is not None:
            try:
                await barrier(target_lease_id, floor_epoch)
            except Exception as exc:  # noqa: BLE001 — abort, never force through
                await self._abort(registry, tenant_id, broadcast_id, floor_epoch)
                self.logger.warning(
                    "broadcast %s: handoff barrier failed at epoch %d: %s",
                    broadcast_id,
                    floor_epoch,
                    exc,
                )
                raise BroadcastError(
                    BroadcastReason.STALE_FLOOR_EPOCH,
                    message=("handoff barrier failed; floor left idle — retry the grant"),
                ) from exc

        if target_lease_id is None:
            # Nobody eligible: leave the floor idle rather than granting it to
            # a participant we cannot verify.
            await self._abort(registry, tenant_id, broadcast_id, floor_epoch)
            descriptor = await registry.get(tenant_id, broadcast_id)
            assert descriptor is not None
            return HandoffResult(descriptor, previous_speaker, floor_epoch)

        # 4. Only now is a speaker permitted again.
        try:
            granted = await registry.commit_floor(tenant_id, broadcast_id, target_lease_id, floor_epoch)
        except BroadcastError:
            await self._abort(registry, tenant_id, broadcast_id, floor_epoch)
            raise

        await self._notify(
            target_lease_id,
            {
                "type": FLOOR_STATE,
                "granted": True,
                "floor_epoch": granted.floor_epoch,
            },
        )
        self.logger.info(
            "broadcast %s: floor granted to %s at epoch %d (was %s)",
            broadcast_id,
            target_lease_id,
            granted.floor_epoch,
            previous_speaker or "-",
        )
        return HandoffResult(granted, previous_speaker, granted.floor_epoch)

    async def _abort(
        self,
        registry: BroadcastRegistry,
        tenant_id: str,
        broadcast_id: str,
        floor_epoch: int,
    ) -> None:
        """Return the floor to idle, tolerating a barrier that already moved."""
        try:
            await registry.abort_floor(tenant_id, broadcast_id, floor_epoch)
        except BroadcastError:
            self.logger.debug(
                "broadcast %s: abort_floor at epoch %d was already superseded",
                broadcast_id,
                floor_epoch,
            )


__all__ = [
    "FLOOR_REVOKED",
    "BroadcastControlService",
    "FLOOR_STATE",
    "FloorCoordinator",
    "HandoffResult",
    "Notifier",
    "validate_audio_authority",
]
