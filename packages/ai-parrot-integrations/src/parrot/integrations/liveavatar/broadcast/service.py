"""Broadcast facade and owner reconciliation watchdog (FEAT-537 — Module 4/5).

:class:`BroadcastService` is the single object the HTTP API (TASK-2962), the
control WebSocket (TASK-2960) and the runnable example (TASK-2963) depend on.
It owns the *policy*: scope and authority checks, who starts the producer, when
a seat is released, and what a dead worker's broadcast is cleaned up into.

Two invariants shape the design:

* **Exactly one producer per broadcast, ever.**  ``reserve_viewer`` decides the
  moderator atomically and reports ``is_first`` to exactly one caller; only that
  caller races for ``claim_owner``, and only the winner starts media.  A loser
  (possible when the first admission's worker dies mid-startup) serves its
  participants through the worker relay instead of starting a second producer —
  spec §2 forbids migrating a live conversation.
* **Reconciliation fails closed.**  When Redis or LiveKit is unreachable the
  reconciler retains seats and records ``reconciliation_uncertain`` rather than
  releasing them; over-admitting a room is worse than a stuck seat, which the
  next healthy pass clears.

After an owner dies the watchdog can remove the room's participants, but it
does **not** hold the owner-only vendor token, so it cannot confirm that the
LiveAvatar session stopped.  That is reported honestly as
``orphaned_vendor_session`` instead of being assumed (spec §7).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from parrot.integrations.liveavatar.broadcast.errors import (
    BroadcastError,
    BroadcastTerminal,
    NotModerator,
)
from parrot.integrations.liveavatar.broadcast.floor import (
    FloorCoordinator,
    HandoffResult,
)
from parrot.integrations.liveavatar.broadcast.models import (
    VIEWER_CREDENTIAL_TTL_S,
    BroadcastDescriptor,
    BroadcastPublicState,
    BroadcastReason,
    BroadcastState,
    ParticipantPrincipal,
    ViewerJoinResponse,
    ViewerLease,
)
from parrot.integrations.liveavatar.broadcast.registry import (
    Admission,
    BroadcastRegistry,
    ExpiryKind,
)
from parrot.integrations.liveavatar.broadcast.session import BroadcastSession
from parrot.integrations.liveavatar.broadcast.voice_relay import BroadcastVoiceSession
from parrot.integrations.liveavatar.broadcast.worker_transport import (
    LocalSpeakerInput,
    RemoteSpeakerInput,
    SpeakerInput,
    WorkerAddressRegistry,
)
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager

#: How often the reconciler runs.  Spec §2: "A watchdog checks at most every
#: 5 seconds".
RECONCILE_INTERVAL_S: float = 5.0

#: Target for fencing plus LiveKit/registry cleanup after owner death.
CLEANUP_TARGET_S: float = 30.0

_logger = logging.getLogger(__name__)


class BroadcastNotReady(BroadcastError):
    """Media is still initialising; the caller should retry shortly.

    Distinct from a failure: HTTP maps it to a **retryable** 409 while the
    broadcast is ``starting``, which is what lets a browser poll for its room
    credentials without the server pretending they exist yet (spec §2).
    """

    status = 409


@dataclass
class _Producer:
    """Live, process-local media objects for one owned broadcast."""

    session: BroadcastSession
    voice: BroadcastVoiceSession
    owner_epoch: int
    bot: Any = None


@dataclass
class ReconcileReport:
    """What one reconciliation pass observed and did.

    Attributes:
        fenced_owners: Broadcast ids whose dead owner was fenced.
        removed_participants: ``(room, identity)`` pairs evicted from LiveKit.
        released_leases: Seats released after their participant was removed.
        elected_moderators: ``(broadcast_id, lease_id)`` successions completed.
        orphaned_vendor_sessions: Broadcast ids whose LiveAvatar session could
            not be confirmed stopped, because the owner-only vendor token died
            with the owner.
        uncertain: Broadcast ids where Redis or LiveKit was unreachable, so
            seats were deliberately retained.
    """

    fenced_owners: List[str] = field(default_factory=list)
    removed_participants: List[Tuple[str, str]] = field(default_factory=list)
    released_leases: List[str] = field(default_factory=list)
    elected_moderators: List[Tuple[str, str]] = field(default_factory=list)
    orphaned_vendor_sessions: List[str] = field(default_factory=list)
    uncertain: List[str] = field(default_factory=list)


def default_principal_resolver(
    user: Any, agent_id: str, *, tenant_id: str = "default"
) -> ParticipantPrincipal:
    """Map an authenticated user to a scoped principal.

    The default takes the tenant from server configuration, never from the
    request: a client-chosen tenant would defeat the whole scoping model.
    Deployments with real multi-tenancy inject their own resolver.

    Args:
        user: An ``AuthenticatedUser`` or a mapping with ``user_id``.
        agent_id: Agent being addressed.
        tenant_id: Server-configured tenant.

    Returns:
        A scoped :class:`ParticipantPrincipal`.

    Raises:
        BroadcastError: When the caller is unauthenticated.
    """
    if user is None:
        raise BroadcastError(message="authentication required")
    if isinstance(user, dict):
        user_id = str(user.get("user_id") or "")
        username = str(user.get("username") or user_id)
        roles = list(user.get("roles") or [])
    else:
        user_id = str(getattr(user, "user_id", "") or "")
        username = str(getattr(user, "username", "") or user_id)
        roles = list(getattr(user, "roles", []) or [])
    if not user_id:
        raise BroadcastError(message="authenticated user has no id")
    return ParticipantPrincipal(
        user_id=user_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        display_name=username,
        roles=roles,
    )


class BroadcastService:
    """Authority, lifecycle and cross-worker routing for moderated broadcasts.

    Args:
        registry: Shared state store (Redis in production).
        room_manager: LiveKit room and token operations.
        nova_bot_factory: Builds the single VoiceBot a broadcast uses.  Separate
            from the handler's general ``bot_factory`` because a broadcast fixes
            the provider to Nova for its lifetime (spec §2).
        worker_id: Opaque id of this worker.  Never a network address.
        worker_registry: Resolves other workers' relay URLs.
        principal_resolver: ``(user, agent_id) -> ParticipantPrincipal``.
        authorize_agent: ``(principal, agent_id) -> bool``.  A valid login is
            explicitly not sufficient (spec §2).
        clock: Injected clock for deterministic watchdog tests.
        session_factory: Override for :class:`BroadcastSession` construction.
        voice_session_factory: Override for :class:`BroadcastVoiceSession`.
        reconcile_interval_s: Watchdog period.
        credential_ttl_s: Admission-credential lifetime.
    """

    def __init__(
        self,
        registry: BroadcastRegistry,
        room_manager: LiveKitRoomManager,
        nova_bot_factory: Optional[Callable[[], Any]] = None,
        worker_id: Optional[str] = None,
        *,
        worker_registry: Optional[WorkerAddressRegistry] = None,
        principal_resolver: Optional[Callable[..., ParticipantPrincipal]] = None,
        authorize_agent: Optional[Callable[[ParticipantPrincipal, str], bool]] = None,
        clock: Optional[Callable[[], float]] = None,
        session_factory: Optional[Callable[..., Any]] = None,
        voice_session_factory: Optional[Callable[..., Any]] = None,
        reconcile_interval_s: float = RECONCILE_INTERVAL_S,
        credential_ttl_s: int = VIEWER_CREDENTIAL_TTL_S,
        worker_token: Optional[str] = None,
    ) -> None:
        self.registry = registry
        self.room_manager = room_manager
        self.nova_bot_factory = nova_bot_factory
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        self.worker_registry = worker_registry or WorkerAddressRegistry()
        self._resolve_principal = principal_resolver or default_principal_resolver
        self._authorize_agent = authorize_agent or (lambda _principal, _agent: True)
        self._clock = clock or time.time
        self._session_factory = session_factory or BroadcastSession
        self._voice_session_factory = voice_session_factory or BroadcastVoiceSession
        self._reconcile_interval_s = reconcile_interval_s
        self._credential_ttl_s = credential_ttl_s
        self._worker_token = worker_token

        self._producers: Dict[Tuple[str, str], _Producer] = {}
        self._connections: Dict[Tuple[str, str, str], ViewerJoinResponse] = {}
        self._controls: Dict[Tuple[str, str], Dict[str, Callable[..., Any]]] = {}
        self._known: set[Tuple[str, str]] = set()
        self._start_locks: Dict[Tuple[str, str], asyncio.Lock] = {}
        self._reconciler: Optional[asyncio.Task[None]] = None
        self._closed = False

        self.coordinator = FloorCoordinator(notifier=self._notify_lease)
        self.logger = logging.getLogger(__name__)

    # ── Scope and authority ────────────────────────────────────────────

    async def resolve_principal(self, user: Any, agent_id: str) -> ParticipantPrincipal:
        """Resolve and authorize a caller for one agent.

        Args:
            user: The authenticated user.
            agent_id: Agent being addressed.

        Returns:
            The scoped principal.

        Raises:
            BroadcastError: When the principal may not use this agent.  Being
                logged in is necessary but never sufficient (spec §2).
        """
        principal = self._resolve_principal(user, agent_id)
        if not self._authorize_agent(principal, agent_id):
            raise BroadcastError(message="not authorized for this agent")
        return principal

    def _require_scope(self, principal: ParticipantPrincipal, agent_id: str) -> None:
        """Reject a principal scoped to a different agent.

        Raises:
            BroadcastError: On an agent-scope mismatch.
        """
        if principal.agent_id != agent_id:
            raise BroadcastError(message="principal is scoped to a different agent")

    async def _descriptor_in_scope(
        self, principal: ParticipantPrincipal, broadcast_id: str
    ) -> BroadcastDescriptor:
        """Fetch a descriptor, treating out-of-scope ids as absent.

        Returns:
            The descriptor.

        Raises:
            BroadcastTerminal: For an unknown or out-of-scope broadcast, which
                the HTTP layer renders as 404 — an out-of-scope id must not be
                distinguishable from a nonexistent one.
        """
        descriptor = await self.registry.get(principal.tenant_id, broadcast_id)
        if descriptor is None or descriptor.agent_id != principal.agent_id:
            raise BroadcastTerminal(message="unknown broadcast")
        return descriptor

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def create_broadcast(
        self, principal: ParticipantPrincipal, agent_id: str
    ) -> BroadcastDescriptor:
        """Create a pending broadcast.

        Creation confers **no** moderator authority: the first successful
        admission decides that (spec §2 step 1).

        Args:
            principal: The authorized creator.
            agent_id: Agent the broadcast speaks for.

        Returns:
            The pending descriptor.
        """
        self._require_scope(principal, agent_id)
        broadcast_id = f"bc-{uuid.uuid4().hex[:16]}"
        descriptor = BroadcastDescriptor(
            broadcast_id=broadcast_id,
            tenant_id=principal.tenant_id,
            agent_id=agent_id,
            creator_user_id=principal.user_id,
            voice_session_id=f"broadcast-{broadcast_id}",
            room_name=f"bcast-{broadcast_id}",
        )
        stored = await self.registry.create(descriptor)
        self._known.add((principal.tenant_id, broadcast_id))
        self.logger.info(
            "broadcast %s created by %s for agent %s",
            broadcast_id,
            principal.user_id,
            agent_id,
        )
        return stored

    async def get_public_state(
        self, principal: ParticipantPrincipal, agent_id: str, broadcast_id: str
    ) -> BroadcastPublicState:
        """Return the browser-safe projection for an in-scope participant."""
        self._require_scope(principal, agent_id)
        descriptor = await self._descriptor_in_scope(principal, broadcast_id)
        return await self._project(descriptor)

    async def _project(
        self, descriptor: BroadcastDescriptor
    ) -> BroadcastPublicState:
        """Build the public state, folding in producer-owned media facts.

        ``BroadcastRegistry.transition`` has no parameters for the room or the
        publisher identities (TASK-2958's completion note flags this), so the
        service is where the live media state is joined onto the durable state.
        """
        leases = await self.registry.list_leases(
            descriptor.tenant_id, descriptor.broadcast_id
        )
        producer = self._producers.get(
            (descriptor.tenant_id, descriptor.broadcast_id)
        )
        if producer is not None:
            media = producer.session.media_state()
            descriptor = descriptor.model_copy(
                update={
                    "room_name": media["room_name"],
                    "avatar_identity": media["avatar_identity"],
                    "direct_identity": media["direct_identity"],
                    "liveavatar_session_id": media["liveavatar_session_id"],
                }
            )
        return descriptor.to_public_state(viewer_count=len(leases))

    async def join(
        self, principal: ParticipantPrincipal, agent_id: str, broadcast_id: str
    ) -> Admission:
        """Reserve a seat, starting the producer on the first admission only.

        Args:
            principal: The admitted participant.
            agent_id: Agent scope.
            broadcast_id: Broadcast to join.

        Returns:
            The :class:`Admission` — ``(lease, is_first)``.

        Raises:
            ViewerLimitReached: When the ten seats are taken.
            BroadcastTerminal: When the broadcast ended or is out of scope.
        """
        self._require_scope(principal, agent_id)
        await self._descriptor_in_scope(principal, broadcast_id)
        self._known.add((principal.tenant_id, broadcast_id))

        identity = f"viewer-{uuid.uuid4().hex[:16]}"
        admission = await self.registry.reserve_viewer(
            principal.tenant_id, broadcast_id, principal, identity
        )
        if admission.is_first:
            await self._claim_and_start(principal.tenant_id, broadcast_id)
        await self._publish_state(principal.tenant_id, broadcast_id)
        return admission

    async def _claim_and_start(self, tenant_id: str, broadcast_id: str) -> None:
        """Race for ownership; start media only if this worker won.

        A worker that loses the race does **not** start a second producer — it
        will serve its participants through the relay instead.
        """
        claimed, owner_epoch = await self.registry.claim_owner(
            tenant_id, broadcast_id, self.worker_id
        )
        if not claimed:
            self.logger.info(
                "broadcast %s: another worker owns the producer (epoch %d)",
                broadcast_id,
                owner_epoch,
            )
            return
        await self.start_producer(tenant_id, broadcast_id, owner_epoch)

    async def start_producer(
        self, tenant_id: str, broadcast_id: str, owner_epoch: int
    ) -> Optional[BroadcastSession]:
        """Bring up the media session and the broadcast-owned voice session.

        Guarded by a per-broadcast lock and an existence check, so concurrent
        first-admissions on the same worker cannot produce two producers even
        before the registry's own atomicity is considered.

        Args:
            tenant_id: Tenant scope.
            broadcast_id: Broadcast to produce.
            owner_epoch: Ownership generation this producer runs under.

        Returns:
            The started session, or ``None`` when one already existed.
        """
        key = (tenant_id, broadcast_id)
        lock = self._start_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self._producers:
                return self._producers[key].session

            descriptor = await self.registry.get(tenant_id, broadcast_id)
            if descriptor is None:
                return None

            session = self._session_factory(
                descriptor,
                self.registry,
                self.room_manager,
                self.worker_id,
                owner_epoch,
            )
            bot = self.nova_bot_factory() if self.nova_bot_factory else None
            voice = self._build_voice_session(descriptor, session, bot)
            voice.set_fanout(self._make_fanout(tenant_id, broadcast_id))
            self._producers[key] = _Producer(
                session=session, voice=voice, owner_epoch=owner_epoch, bot=bot
            )
            self._known.add(key)

            try:
                await session.start()
            except Exception:  # noqa: BLE001 — the session already marked failed
                self.logger.exception(
                    "broadcast %s: producer startup failed", broadcast_id
                )
                self._producers.pop(key, None)
                raise
            await self._publish_state(tenant_id, broadcast_id)
            return session

    def _build_voice_session(
        self, descriptor: BroadcastDescriptor, session: Any, bot: Any
    ) -> Any:
        """Construct the broadcast-owned voice session.

        The conversation key is the broadcast's stable ``voice_session_id`` —
        never the current speaker's — so the floor can move without the agent
        losing the conversation (spec §2).
        """
        from parrot.voice.handler import _AskStreamVoiceClient

        client = _AskStreamVoiceClient(bot) if bot is not None else None
        return self._voice_session_factory(
            client=client,
            system_prompt=getattr(bot, "system_prompt", "") or "",
            voice_config=getattr(bot, "voice_config", None),
            session_id=descriptor.voice_session_id or descriptor.broadcast_id,
            broadcast=session,
        )

    async def connection(
        self, principal: ParticipantPrincipal, broadcast_id: str, lease_id: str
    ) -> ViewerJoinResponse:
        """Issue this lease's subscribe-only room credentials.

        Idempotent per lease: the same identity and token are returned on every
        call, so a retrying browser cannot consume a second seat.

        Args:
            principal: The lease owner.
            broadcast_id: Broadcast concerned.
            lease_id: The admitted lease.

        Returns:
            The browser-safe :class:`ViewerJoinResponse`.

        Raises:
            BroadcastError: When the lease is not owned by this principal.
            BroadcastNotReady: While media is still initialising (retryable).
        """
        descriptor = await self._descriptor_in_scope(principal, broadcast_id)
        lease = await self.get_lease(principal.tenant_id, broadcast_id, lease_id)
        if lease is None or lease.principal.user_id != principal.user_id:
            raise BroadcastError(message="lease is not owned by this principal")

        cache_key = (principal.tenant_id, broadcast_id, lease_id)
        cached = self._connections.get(cache_key)
        if cached is not None:
            return cached

        if descriptor.state in (BroadcastState.PENDING, BroadcastState.STARTING):
            raise BroadcastNotReady(message="media is still starting; retry shortly")
        if descriptor.is_terminal:
            raise BroadcastTerminal(reason=descriptor.failure_reason)

        public = await self._project(descriptor)
        room = public.selected_identity and descriptor.room_name or descriptor.room_name
        if not room:
            raise BroadcastNotReady(message="room is not allocated yet")

        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._credential_ttl_s
        )
        token = await asyncio.to_thread(
            self.room_manager.mint_viewer_token,
            room,
            lease.livekit_identity,
            ttl_s=self._credential_ttl_s,
        )
        response = ViewerJoinResponse(
            public_state=public,
            lease_id=lease_id,
            livekit_url=self.room_manager.url,
            room=room,
            client_token=token,
            expires_at=expires_at,
        )
        self._connections[cache_key] = response
        return response

    async def leave(
        self, principal: ParticipantPrincipal, broadcast_id: str, lease_id: str
    ) -> None:
        """Release a seat and run whatever succession it triggers.

        Args:
            principal: The lease owner.
            broadcast_id: Broadcast concerned.
            lease_id: The lease being released.
        """
        tenant_id = principal.tenant_id
        lease = await self.get_lease(tenant_id, broadcast_id, lease_id)
        if lease is not None and lease.principal.user_id != principal.user_id:
            raise BroadcastError(message="lease is not owned by this principal")

        outcome = await self.registry.release_viewer(tenant_id, broadcast_id, lease_id)
        self._connections.pop((tenant_id, broadcast_id, lease_id), None)

        if lease is not None:
            descriptor = await self.registry.get(tenant_id, broadcast_id)
            room = descriptor.room_name if descriptor else None
            if room:
                with contextlib.suppress(Exception):
                    await self.room_manager.remove_participant(
                        room, lease.livekit_identity
                    )

        await self._settle_departure(tenant_id, broadcast_id, outcome, lease_id)

    async def _settle_departure(
        self, tenant_id: str, broadcast_id: str, outcome: Any, lease_id: str
    ) -> None:
        """Complete the barrier a departure opened, or tear the producer down."""
        producer = self._producers.get((tenant_id, broadcast_id))
        session = producer.session if producer else None

        if outcome.audience_empty:
            await self.stop_producer(
                tenant_id,
                broadcast_id,
                final_state=BroadcastState.ENDED,
                reason=BroadcastReason.AUDIENCE_EMPTY,
            )
            return

        if outcome.new_moderator:
            descriptor = await self.registry.get(tenant_id, broadcast_id)
            if descriptor is not None:
                with contextlib.suppress(BroadcastError):
                    await self.coordinator.succeed_moderator(
                        self.registry,
                        session,
                        tenant_id=tenant_id,
                        broadcast_id=broadcast_id,
                        new_moderator_lease_id=outcome.new_moderator,
                        floor_epoch=descriptor.floor_epoch,
                        previous_speaker=lease_id,
                    )
        elif outcome.floor_returned_to:
            descriptor = await self.registry.get(tenant_id, broadcast_id)
            if descriptor is not None:
                with contextlib.suppress(BroadcastError):
                    await self.coordinator.succeed_moderator(
                        self.registry,
                        session,
                        tenant_id=tenant_id,
                        broadcast_id=broadcast_id,
                        new_moderator_lease_id=outcome.floor_returned_to,
                        floor_epoch=descriptor.floor_epoch,
                        previous_speaker=lease_id,
                    )
        await self._publish_state(tenant_id, broadcast_id)

    async def stop(
        self, principal: ParticipantPrincipal, broadcast_id: str
    ) -> BroadcastDescriptor:
        """Moderator-only broadcast-wide stop.

        Records a **durable** desired state; the owning worker observes it
        within a second, wherever it runs (spec §2 cross-worker stop).

        Args:
            principal: The caller.
            broadcast_id: Broadcast to stop.

        Returns:
            The updated descriptor.

        Raises:
            NotModerator: For anyone else — including the creator.
        """
        tenant_id = principal.tenant_id
        descriptor = await self._descriptor_in_scope(principal, broadcast_id)
        lease_id = await self._lease_id_for(tenant_id, broadcast_id, principal)
        if lease_id is None or descriptor.moderator_lease_id != lease_id:
            raise NotModerator(message="only the current moderator may stop")

        updated = await self.registry.request_stop(tenant_id, broadcast_id, lease_id)
        # If we own the producer, act immediately rather than waiting a second.
        if (tenant_id, broadcast_id) in self._producers:
            await self.stop_producer(
                tenant_id,
                broadcast_id,
                final_state=BroadcastState.ENDED,
                reason=BroadcastReason.STOPPED_BY_MODERATOR,
            )
        await self._publish_state(tenant_id, broadcast_id)
        return updated

    async def stop_producer(
        self,
        tenant_id: str,
        broadcast_id: str,
        *,
        final_state: BroadcastState = BroadcastState.ENDED,
        reason: Optional[BroadcastReason] = None,
    ) -> None:
        """Tear down the local producer, if this worker owns one."""
        producer = self._producers.pop((tenant_id, broadcast_id), None)
        if producer is None:
            return
        with contextlib.suppress(Exception):
            await producer.session.aclose(final_state=final_state, reason=reason)
        with contextlib.suppress(Exception):
            await producer.voice.close()
        self.logger.info(
            "broadcast %s: producer stopped (%s)",
            broadcast_id,
            reason.value if reason else final_state.value,
        )

    # ── Hands and floor ────────────────────────────────────────────────

    async def raise_hand(
        self, principal: ParticipantPrincipal, broadcast_id: str, lease_id: str
    ) -> BroadcastPublicState:
        """Record an idempotent raise-hand.  Grants no microphone permission."""
        await self._require_own_lease(principal, broadcast_id, lease_id)
        descriptor = await self.registry.raise_hand(
            principal.tenant_id, broadcast_id, lease_id
        )
        await self._publish_state(principal.tenant_id, broadcast_id)
        return await self._project(descriptor)

    async def cancel_hand(
        self, principal: ParticipantPrincipal, broadcast_id: str, lease_id: str
    ) -> BroadcastPublicState:
        """Withdraw the caller's own hand request."""
        await self._require_own_lease(principal, broadcast_id, lease_id)
        descriptor = await self.registry.cancel_hand(
            principal.tenant_id, broadcast_id, lease_id
        )
        await self._publish_state(principal.tenant_id, broadcast_id)
        return await self._project(descriptor)

    async def dismiss_hand(
        self, principal: ParticipantPrincipal, broadcast_id: str, target_lease_id: str
    ) -> BroadcastPublicState:
        """Moderator-only dismissal of somebody else's request."""
        tenant_id = principal.tenant_id
        moderator_lease_id = await self._lease_id_for(
            tenant_id, broadcast_id, principal
        )
        if moderator_lease_id is None:
            raise NotModerator(message="caller holds no lease")
        descriptor = await self.registry.dismiss_hand(
            tenant_id, broadcast_id, moderator_lease_id, target_lease_id
        )
        await self._publish_state(tenant_id, broadcast_id)
        return await self._project(descriptor)

    async def set_floor(
        self,
        principal: ParticipantPrincipal,
        broadcast_id: str,
        target_lease_id: Optional[str],
        expected_version: int,
    ) -> HandoffResult:
        """Grant, revoke or reclaim the speaking floor.

        Args:
            principal: Must be the current moderator.
            broadcast_id: Broadcast concerned.
            target_lease_id: Lease to grant, or ``None`` to revoke.
            expected_version: Compare-and-set guard.

        Returns:
            The completed handoff.

        Raises:
            NotModerator: If the caller is not the current moderator.
            StaleVersion: On a concurrent grant.
            BroadcastError: With ``stale_floor_epoch`` if the barrier fails.
        """
        tenant_id = principal.tenant_id
        moderator_lease_id = await self._lease_id_for(
            tenant_id, broadcast_id, principal
        )
        if moderator_lease_id is None:
            raise NotModerator(message="caller holds no lease")
        producer = self._producers.get((tenant_id, broadcast_id))
        result = await self.coordinator.handoff(
            self.registry,
            producer.session if producer else None,
            tenant_id=tenant_id,
            broadcast_id=broadcast_id,
            moderator_lease_id=moderator_lease_id,
            target_lease_id=target_lease_id,
            expected_version=expected_version,
        )
        await self._publish_state(tenant_id, broadcast_id)
        return result

    async def release_floor(
        self, tenant_id: str, broadcast_id: str, speaker_lease_id: str
    ) -> HandoffResult:
        """Finish Speaking — return the floor to the moderator via the barrier."""
        producer = self._producers.get((tenant_id, broadcast_id))
        result = await self.coordinator.release(
            self.registry,
            producer.session if producer else None,
            tenant_id=tenant_id,
            broadcast_id=broadcast_id,
            speaker_lease_id=speaker_lease_id,
        )
        await self._publish_state(tenant_id, broadcast_id)
        return result

    # ── Control-socket protocol surface (TASK-2960) ────────────────────

    async def get_descriptor(
        self, tenant_id: str, broadcast_id: str
    ) -> Optional[BroadcastDescriptor]:
        """Return the current descriptor, or ``None``."""
        return await self.registry.get(tenant_id, broadcast_id)

    async def get_lease(
        self, tenant_id: str, broadcast_id: str, lease_id: str
    ) -> Optional[ViewerLease]:
        """Return one lease, or ``None``."""
        for lease in await self.registry.list_leases(tenant_id, broadcast_id):
            if lease.lease_id == lease_id:
                return lease
        return None

    async def heartbeat(
        self, tenant_id: str, broadcast_id: str, lease_id: str
    ) -> None:
        """Record a control heartbeat.  Never bumps the public version."""
        with contextlib.suppress(BroadcastError):
            await self.registry.heartbeat_control(tenant_id, broadcast_id, lease_id)

    async def attach_control(
        self, tenant_id: str, broadcast_id: str, lease_id: str, send: Any
    ) -> None:
        """Register a control socket for in-process fan-out."""
        self._controls.setdefault((tenant_id, broadcast_id), {})[lease_id] = send
        self._known.add((tenant_id, broadcast_id))

    async def detach_control(
        self, tenant_id: str, broadcast_id: str, lease_id: str
    ) -> None:
        """Deregister a control socket."""
        self._controls.get((tenant_id, broadcast_id), {}).pop(lease_id, None)

    # ``subscribe``/``unsubscribe`` are the broadcast-wide aliases used by the
    # example; control sockets use the lease-scoped pair above.
    async def subscribe(
        self, tenant_id: str, broadcast_id: str, lease_id: str, send: Any
    ) -> None:
        """Alias of :meth:`attach_control`."""
        await self.attach_control(tenant_id, broadcast_id, lease_id, send)

    async def unsubscribe(
        self, tenant_id: str, broadcast_id: str, lease_id: str
    ) -> None:
        """Alias of :meth:`detach_control`."""
        await self.detach_control(tenant_id, broadcast_id, lease_id)

    async def public_state(self, tenant_id: str, broadcast_id: str) -> Dict[str, Any]:
        """Return the public projection as a JSON-safe dict."""
        descriptor = await self.registry.get(tenant_id, broadcast_id)
        if descriptor is None:
            return {}
        return (await self._project(descriptor)).model_dump(mode="json")

    async def bind_speaker_socket(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        socket_id: str,
        floor_epoch: int,
    ) -> bool:
        """Bind the single microphone socket permitted to send audio."""
        return await self.registry.bind_speaker_socket(
            tenant_id, broadcast_id, lease_id, socket_id, floor_epoch
        )

    async def unbind_speaker_socket(
        self, tenant_id: str, broadcast_id: str, lease_id: str, socket_id: str
    ) -> bool:
        """Release a microphone-socket binding."""
        return await self.registry.unbind_speaker_socket(
            tenant_id, broadcast_id, lease_id, socket_id
        )

    def voice_session(self, tenant_id: str, broadcast_id: str) -> Any:
        """Return the broadcast-owned voice session on this worker, or ``None``."""
        producer = self._producers.get((tenant_id, broadcast_id))
        return producer.voice if producer else None

    def media_session(self, tenant_id: str, broadcast_id: str) -> Any:
        """Return the :class:`BroadcastSession` on this worker, or ``None``."""
        producer = self._producers.get((tenant_id, broadcast_id))
        return producer.session if producer else None

    def owner_epoch(self, tenant_id: str, broadcast_id: str) -> Optional[int]:
        """Ownership generation of the local producer, or ``None``."""
        producer = self._producers.get((tenant_id, broadcast_id))
        return producer.owner_epoch if producer else None

    async def attach_speaker_input(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        principal: ParticipantPrincipal,
        floor_epoch: int,
    ) -> SpeakerInput:
        """Return the sink this worker should feed the speaker's audio into.

        Local when this worker owns the producer; otherwise an authenticated
        relay to the owner, whose address comes from the worker registry and
        never from a client.

        Args:
            tenant_id: Tenant scope.
            broadcast_id: Broadcast concerned.
            lease_id: The speaking lease.
            principal: The speaker's principal.
            floor_epoch: Floor epoch this input was authorised under.

        Returns:
            A :class:`SpeakerInput`.

        Raises:
            BroadcastError: When no producer can be reached.
        """
        producer = self._producers.get((tenant_id, broadcast_id))
        if producer is not None:
            return LocalSpeakerInput(
                producer.voice, lease_id, principal, floor_epoch
            )

        descriptor = await self.registry.get(tenant_id, broadcast_id)
        if descriptor is None or not descriptor.owner_worker_id:
            raise BroadcastError(
                BroadcastReason.OWNER_LOST, message="no producer owns this broadcast"
            )
        url = await self.worker_registry.resolve(descriptor.owner_worker_id)
        if not url:
            raise BroadcastError(
                BroadcastReason.OWNER_LOST,
                message="producer worker is not reachable",
            )
        return RemoteSpeakerInput(
            url,
            tenant_id=tenant_id,
            broadcast_id=broadcast_id,
            owner_epoch=descriptor.owner_epoch,
            lease_id=lease_id,
            floor_epoch=floor_epoch,
            token=self._worker_token,
        )

    # ── Fan-out ────────────────────────────────────────────────────────

    def _make_fanout(
        self, tenant_id: str, broadcast_id: str
    ) -> Callable[[Dict[str, Any]], Awaitable[None]]:
        """Build the relay's fan-out: one frame to every attached socket."""

        async def _fanout(frame: Dict[str, Any]) -> None:
            await self._broadcast_frame(tenant_id, broadcast_id, frame)

        return _fanout

    async def _broadcast_frame(
        self, tenant_id: str, broadcast_id: str, frame: Dict[str, Any]
    ) -> None:
        """Send one frame to every control socket, tolerating dead ones."""
        for send in list(self._controls.get((tenant_id, broadcast_id), {}).values()):
            with contextlib.suppress(Exception):
                await send(frame)

    async def _notify_lease(self, lease_id: str, frame: Dict[str, Any]) -> None:
        """Send one frame to a single lease's control socket, if attached."""
        for controls in self._controls.values():
            send = controls.get(lease_id)
            if send is not None:
                with contextlib.suppress(Exception):
                    await send(frame)
                return

    async def _publish_state(self, tenant_id: str, broadcast_id: str) -> None:
        """Push the current public projection to every attached socket.

        Advisory only: the durable state is authoritative and a browser that
        misses this recovers on its next poll (spec §2).
        """
        if not self._controls.get((tenant_id, broadcast_id)):
            return
        with contextlib.suppress(Exception):
            state = await self.public_state(tenant_id, broadcast_id)
            await self._broadcast_frame(
                tenant_id, broadcast_id, {"type": "broadcast_state", "state": state}
            )

    async def _require_own_lease(
        self, principal: ParticipantPrincipal, broadcast_id: str, lease_id: str
    ) -> ViewerLease:
        """Fetch a lease and verify the caller owns it.

        Raises:
            BroadcastError: When the lease is unknown or owned by someone else.
        """
        lease = await self.get_lease(principal.tenant_id, broadcast_id, lease_id)
        if lease is None or lease.principal.user_id != principal.user_id:
            raise BroadcastError(message="lease is not owned by this principal")
        return lease

    async def _lease_id_for(
        self, tenant_id: str, broadcast_id: str, principal: ParticipantPrincipal
    ) -> Optional[str]:
        """Return the lease this principal holds in a broadcast, if any."""
        for lease in await self.registry.list_leases(tenant_id, broadcast_id):
            if lease.principal.user_id == principal.user_id:
                return lease.lease_id
        return None

    # ── Reconciliation watchdog ────────────────────────────────────────

    def start_reconciler(self) -> None:
        """Start the background watchdog (idempotent)."""
        if self._reconciler is None or self._reconciler.done():
            self._reconciler = asyncio.create_task(
                self.run_reconciler(), name=f"broadcast-reconciler-{self.worker_id}"
            )

    async def run_reconciler(self) -> None:
        """Run :meth:`reconcile_once` on a fixed period until closed."""
        while not self._closed:
            await asyncio.sleep(self._reconcile_interval_s)
            if self._closed:
                return
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — a watchdog must not die
                self.logger.exception("broadcast reconciler pass failed")

    async def reconcile_once(self) -> ReconcileReport:
        """One reconciliation pass over every broadcast this worker knows.

        Returns:
            What the pass observed and did.
        """
        report = ReconcileReport()
        for tenant_id, broadcast_id in list(self._known):
            try:
                events = await self.registry.expire(tenant_id, broadcast_id)
            except Exception:  # noqa: BLE001 — store unreachable: fail closed
                report.uncertain.append(broadcast_id)
                self.logger.warning(
                    "broadcast %s: reconciliation_uncertain (registry unreachable) — "
                    "retaining seats",
                    broadcast_id,
                    exc_info=True,
                )
                continue

            for event in events:
                if event.kind is ExpiryKind.OWNER_LEASE:
                    await self._fence_dead_owner(tenant_id, broadcast_id, report)
                elif event.kind in (
                    ExpiryKind.CONTROL_HEARTBEAT,
                    ExpiryKind.ADMISSION_DEADLINE,
                ):
                    await self._evict_expired_lease(
                        tenant_id, broadcast_id, event.lease_id, report
                    )
                elif event.kind is ExpiryKind.TERMINAL_RETENTION:
                    self._known.discard((tenant_id, broadcast_id))
        return report

    async def _fence_dead_owner(
        self, tenant_id: str, broadcast_id: str, report: ReconcileReport
    ) -> None:
        """Take ownership of an abandoned broadcast and clean it up.

        Claiming ownership advances ``owner_epoch``, which fences the dead
        worker: any of its in-flight registry writes are now rejected, and any
        relay connection still pointed at it closes.
        """
        claimed, owner_epoch = await self.registry.claim_owner(
            tenant_id, broadcast_id, self.worker_id
        )
        if not claimed:
            return
        report.fenced_owners.append(broadcast_id)
        self.logger.warning(
            "broadcast %s: fenced a dead owner at epoch %d", broadcast_id, owner_epoch
        )

        descriptor = await self.registry.get(tenant_id, broadcast_id)
        room = descriptor.room_name if descriptor else None
        if room:
            try:
                identities = await self.room_manager.list_participant_identities(room)
                for identity in identities:
                    await self.room_manager.remove_participant(room, identity)
                    report.removed_participants.append((room, identity))
                await self.room_manager.delete_room(room)
            except Exception:  # noqa: BLE001 — LiveKit unreachable: fail closed
                report.uncertain.append(broadcast_id)
                self.logger.warning(
                    "broadcast %s: reconciliation_uncertain (LiveKit unreachable)",
                    broadcast_id,
                    exc_info=True,
                )

        avatar_was_live = descriptor is not None and (
            descriptor.state is BroadcastState.AVATAR
            or bool(descriptor.liveavatar_session_id)
        )
        if avatar_was_live:
            # The vendor stop call needs the owner-only session token, which
            # died with the owner. Report the orphan rather than claiming a
            # confirmed termination (spec §7).
            #
            # Keyed off the broadcast having *reached* `avatar` rather than off
            # `liveavatar_session_id`, because nothing currently persists that
            # id onto the descriptor — `BroadcastRegistry.transition` has no
            # parameter for it (see TASK-2958's completion note). Using the
            # unpopulated field alone would silently never report an orphan.
            report.orphaned_vendor_sessions.append(broadcast_id)
            self.logger.warning(
                "broadcast %s: orphaned_vendor_session — cannot confirm LiveAvatar "
                "termination without the owner's token; it expires by the "
                "configured max_session_duration",
                broadcast_id,
            )

        with contextlib.suppress(Exception):
            await self.registry.transition(
                tenant_id,
                broadcast_id,
                BroadcastState.FAILED,
                reason=BroadcastReason.OWNER_LOST,
                expected_owner_epoch=owner_epoch,
            )
        await self.stop_producer(
            tenant_id,
            broadcast_id,
            final_state=BroadcastState.FAILED,
            reason=BroadcastReason.OWNER_LOST,
        )

    async def _evict_expired_lease(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: Optional[str],
        report: ReconcileReport,
    ) -> None:
        """Remove an unresponsive participant, then release its seat.

        Order matters and is spec-mandated: remove from the room **first**, so
        a replacement admission can never coexist with a participant that is
        still connected.
        """
        if lease_id is None:
            return
        lease = await self.get_lease(tenant_id, broadcast_id, lease_id)
        descriptor = await self.registry.get(tenant_id, broadcast_id)
        room = descriptor.room_name if descriptor else None
        if lease is not None and room:
            try:
                await self.room_manager.remove_participant(
                    room, lease.livekit_identity
                )
                report.removed_participants.append((room, lease.livekit_identity))
            except Exception:  # noqa: BLE001 — retain the seat, retry next pass
                report.uncertain.append(broadcast_id)
                self.logger.warning(
                    "broadcast %s: could not remove %s — retaining its seat",
                    broadcast_id,
                    lease_id,
                    exc_info=True,
                )
                return

        outcome = await self.registry.release_viewer(tenant_id, broadcast_id, lease_id)
        report.released_leases.append(lease_id)
        if outcome.new_moderator:
            report.elected_moderators.append((broadcast_id, outcome.new_moderator))
        await self._settle_departure(tenant_id, broadcast_id, outcome, lease_id)

    # ── Teardown ───────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Stop the watchdog and every producer this worker owns."""
        self._closed = True
        if self._reconciler is not None:
            self._reconciler.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reconciler
            self._reconciler = None
        for tenant_id, broadcast_id in list(self._producers):
            await self.stop_producer(
                tenant_id,
                broadcast_id,
                final_state=BroadcastState.ENDED,
                reason=BroadcastReason.STOPPED_BY_MODERATOR,
            )
        with contextlib.suppress(Exception):
            await self.worker_registry.unregister(self.worker_id)


__all__ = [
    "CLEANUP_TARGET_S",
    "RECONCILE_INTERVAL_S",
    "BroadcastNotReady",
    "BroadcastService",
    "ReconcileReport",
    "default_principal_resolver",
]
