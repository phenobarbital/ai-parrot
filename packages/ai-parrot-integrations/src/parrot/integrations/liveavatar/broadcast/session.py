"""Producer-side media lifecycle for one broadcast (FEAT-537 — Module 3).

Implements spec §2 "Architectural Design" and "Audio routing, failure and
interruption": one broadcast owns **one** Nova VoiceBot conversation, **one**
LiveAvatar generation session and **one** LiveKit output room, fanned out to up
to ten browsers.

Three properties drive almost every decision in this module:

1. **The direct publisher exists before the avatar does.**  The room and a
   silent ``direct-voice`` publisher are allocated first, so a failed avatar
   startup degrades to audio-only *in the same room the audience already
   joined* instead of stranding them (spec §2 step 3).
2. **Fallback is one-way and never replays ambiguous audio.**  ``avatar →
   audio_only`` has no reverse edge, and on cutover only frames that were
   never handed to the vendor are re-routed.  A frame whose send was in flight
   is *ambiguous* — it may already have been heard — so it is counted and
   dropped, not replayed (spec §2: "duplicate speech and silent loss of all
   subsequent speech are not [acceptable]" — a brief gap is).
3. **Interruption clears software *and* native queues.**  Emptying the Python
   deque is not enough: audio already handed to ``AudioSource`` keeps playing,
   which is why :meth:`RoomAudioPublisher.flush` was fixed in TASK-2956.

Every vendor-timing threshold is a constructor knob rather than a constant,
because the TASK-2950 live gate did **not** run (0/12 scenarios, no
credentials) and so the spec's 15 s / 10 s / 2 s defaults remain *unverified*.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, Optional

from parrot.integrations.liveavatar.avatar_ws import AvatarSendTimeout
from parrot.integrations.liveavatar.broadcast.errors import BroadcastError
from parrot.integrations.liveavatar.broadcast.models import (
    AVATAR_STARTUP_DEADLINE_S,
    HANDOFF_BARRIER_TIMEOUT_S,
    MAX_QUEUED_PCM_BYTES,
    OWNER_RENEW_S,
    BroadcastAudioFrame,
    BroadcastDescriptor,
    BroadcastReason,
    BroadcastState,
)
from parrot.integrations.liveavatar.broadcast.registry import BroadcastRegistry
from parrot.integrations.liveavatar.room_audio_publisher import RoomAudioPublisher
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager
from parrot.integrations.liveavatar.voice_session import (
    AvatarStartupTimeout,
    VoiceAvatarSession,
)

#: Room capacity: ten viewer seats **plus** the avatar and direct publishers.
#: The ten-seat rule itself is enforced by registry reservations, never by
#: LiveKit's own participant cap (spec §7).
ROOM_CAPACITY: int = 12

#: How often the stop flag is polled.  Spec §2: "a durable desired state
#: checked by the owner at least once per second".
STOP_POLL_S: float = 1.0

#: Track name for the direct (fallback) audio publisher.  Deliberately not
#: ``agent-voice``: the avatar and the direct publisher must be distinguishable
#: by the browser when it selects its single audible source.
DIRECT_TRACK_NAME: str = "direct-voice"


class BroadcastSession:
    """Owns the live media resources of one broadcast on the producer worker.

    Live SDK objects never leave this process; only sanitized state reaches
    Redis.  The session is created by the worker that won ``claim_owner`` and
    torn down by :meth:`aclose`.

    Args:
        descriptor: The broadcast this session produces for.
        registry: Shared state store, used for transitions, ownership renewal
            and the stop flag.
        room_manager: LiveKit room/token operations.
        worker_id: Opaque id of the owning worker.
        owner_epoch: Ownership generation this session was started under.  Every
            registry write is fenced by it, so a superseded owner cannot
            transition a broadcast it no longer owns.
        avatar_session_factory: Override for ``VoiceAvatarSession.start``.
        publisher_factory: Override for ``RoomAudioPublisher.start``.
        clock: Monotonic clock, injected for deterministic watchdog tests.
        avatar_startup_deadline_s: Readiness deadline before selecting
            audio-only.  **Unverified default** (spec §2, live gate NOT RUN).
        speech_watchdog_s: Output-progress timeout while speech is expected.
            **Unverified default.**
        send_deadline_s: Per-send vendor deadline.  **Unverified default.**
        max_queued_bytes: Bounded PCM queue — two seconds at 24 kHz mono PCM16.
        max_session_duration_s: Vendor session cap (spec §7: ≤ 600).
    """

    def __init__(
        self,
        descriptor: BroadcastDescriptor,
        registry: BroadcastRegistry,
        room_manager: LiveKitRoomManager,
        worker_id: str,
        owner_epoch: int,
        *,
        avatar_session_factory: Optional[Callable[..., Awaitable[Any]]] = None,
        publisher_factory: Optional[Callable[..., Awaitable[Any]]] = None,
        clock: Optional[Callable[[], float]] = None,
        avatar_startup_deadline_s: float = AVATAR_STARTUP_DEADLINE_S,
        speech_watchdog_s: float = 10.0,
        send_deadline_s: float = 2.0,
        max_queued_bytes: int = MAX_QUEUED_PCM_BYTES,
        max_session_duration_s: int = 600,
    ) -> None:
        self.descriptor = descriptor
        self.registry = registry
        self.room_manager = room_manager
        self.worker_id = worker_id
        self.owner_epoch = owner_epoch

        self._avatar_factory = avatar_session_factory or VoiceAvatarSession.start
        self._publisher_factory = publisher_factory or RoomAudioPublisher.start
        self._clock = clock or time.monotonic

        self._avatar_startup_deadline_s = avatar_startup_deadline_s
        self._speech_watchdog_s = speech_watchdog_s
        self._send_deadline_s = send_deadline_s
        self._max_queued_bytes = max_queued_bytes
        self._max_session_duration_s = max_session_duration_s

        short = descriptor.broadcast_id[:8]
        self.room_name: str = descriptor.room_name or f"bcast-{descriptor.broadcast_id}"
        self.avatar_identity: str = descriptor.avatar_identity or f"avatar-{short}"
        self.direct_identity: str = descriptor.direct_identity or f"direct-{short}"

        self.state: BroadcastState = descriptor.state
        self.output_epoch: int = descriptor.output_epoch
        self.floor_epoch: int = descriptor.floor_epoch
        self.failure_reason: Optional[BroadcastReason] = None

        self._avatar: Any = None
        self._publisher: Any = None

        self._queue: Deque[tuple[int, BroadcastAudioFrame]] = deque()
        self._queued_bytes: int = 0
        #: Frames popped from the queue whose delivery has not returned yet.
        self._inflight: int = 0
        self._wakeup: asyncio.Event = asyncio.Event()
        self._generation: int = 0
        self._acked_generation: int = 0
        self._gen_ack: asyncio.Event = asyncio.Event()

        self._pump_task: Optional[asyncio.Task[None]] = None
        self._owner_task: Optional[asyncio.Task[None]] = None
        self._cutover_lock: asyncio.Lock = asyncio.Lock()
        self._closed: bool = False
        self._teardown_done: bool = False
        self._closing: asyncio.Lock = asyncio.Lock()

        self._last_frame_sent_at: Optional[float] = None
        self._last_speech_event_at: Optional[float] = None

        #: Observability counters, asserted by tests and logged on close.
        self.dropped_stale_frames: int = 0
        self.dropped_overflow_frames: int = 0
        self.dropped_ambiguous_samples: int = 0
        self.forwarded_on_cutover: int = 0

        self.logger = logging.getLogger(__name__)

    # ── Introspection ──────────────────────────────────────────────────

    @property
    def queued_bytes(self) -> int:
        """PCM bytes buffered but not yet handed to a sink."""
        return self._queued_bytes

    @property
    def closed(self) -> bool:
        """Whether :meth:`aclose` has run."""
        return self._closed

    def media_state(self) -> Dict[str, Any]:
        """Sanitized snapshot of producer-owned media facts.

        These are the values the public descriptor needs (selected identity,
        room, epochs) but which :meth:`BroadcastRegistry.transition` has no
        parameters for.  The service layer projects them.

        Returns:
            A credential-free dict.
        """
        return {
            "room_name": self.room_name,
            "avatar_identity": self.avatar_identity,
            "direct_identity": self.direct_identity,
            "state": self.state.value,
            "output_epoch": self.output_epoch,
            "floor_epoch": self.floor_epoch,
            "reason": self.failure_reason.value if self.failure_reason else None,
            "liveavatar_session_id": getattr(
                self._avatar, "liveavatar_session_id", None
            ),
        }

    def _log_state(self, event: str, reason: Optional[BroadcastReason] = None) -> None:
        """Emit one structured INFO line per lifecycle event."""
        self.logger.info(
            "broadcast %s: %s state=%s output_epoch=%d floor_epoch=%d reason=%s",
            self.descriptor.broadcast_id,
            event,
            self.state.value,
            self.output_epoch,
            self.floor_epoch,
            reason.value if reason else "-",
        )

    async def _transition(
        self,
        new_state: BroadcastState,
        *,
        reason: Optional[BroadcastReason] = None,
        output_epoch: Optional[int] = None,
    ) -> None:
        """Record a state change locally and in the registry.

        Registry failures are logged, not raised: the local state is what the
        producer acts on, and a Redis blip must not leave media running while
        the session believes it stopped.
        """
        self.state = new_state
        if output_epoch is not None:
            self.output_epoch = output_epoch
        if reason is not None:
            self.failure_reason = reason
        try:
            await self.registry.transition(
                self.descriptor.tenant_id,
                self.descriptor.broadcast_id,
                new_state,
                output_epoch=output_epoch,
                reason=reason,
                expected_owner_epoch=self.owner_epoch,
            )
        except Exception:  # noqa: BLE001 — local state still governs the media
            self.logger.warning(
                "broadcast %s: registry transition to %s failed",
                self.descriptor.broadcast_id,
                new_state.value,
                exc_info=True,
            )
        self._log_state("transition", reason)

    # ── Startup ────────────────────────────────────────────────────────

    async def start(self) -> BroadcastState:
        """Bring up the room, the direct publisher and then the avatar.

        Order matters: the audience's fallback path must already exist before
        the avatar is attempted, so an avatar failure is a degradation rather
        than an outage.

        An avatar failure at **any** stage selects ``audio_only`` and does not
        raise.  A room or direct-publisher failure is a genuine outage: the
        broadcast goes to ``failed`` with ``livekit_failure`` and the error is
        re-raised, never dressed up as a working fallback (spec AC7).

        Returns:
            The state the broadcast settled in — ``avatar`` or ``audio_only``.

        Raises:
            Exception: Whatever the room or direct publisher raised.
        """
        await self._transition(BroadcastState.STARTING)

        try:
            await self.room_manager.create_room(
                self.room_name, max_participants=ROOM_CAPACITY
            )
            direct_token = self.room_manager.mint_publisher_token(
                self.room_name, self.direct_identity
            )
            self._publisher = await self._publisher_factory(
                livekit_url=self.room_manager.url,
                token=direct_token,
                track_name=DIRECT_TRACK_NAME,
                on_failure=self._on_publisher_failure,
            )
        except Exception as exc:  # noqa: BLE001 — fatal, not a fallback
            self.logger.exception(
                "broadcast %s: LiveKit prerequisites failed",
                self.descriptor.broadcast_id,
            )
            await self._abort(BroadcastReason.LIVEKIT_FAILURE)
            raise exc

        self._start_tasks()

        try:
            avatar_token = self.room_manager.mint_publisher_token(
                self.room_name, self.avatar_identity
            )
            self._avatar = await self._avatar_factory(
                agent_id=self.descriptor.agent_id,
                session_id=self.descriptor.voice_session_id
                or self.descriptor.broadcast_id,
                tenant_id=self.descriptor.tenant_id,
                livekit_url=self.room_manager.url,
                room_name=self.room_name,
                avatar_publisher_token=avatar_token,
                avatar_identity=self.avatar_identity,
                broadcast=True,
                on_event=self._on_avatar_event,
                on_close=self._on_avatar_close,
                send_timeout_s=self._send_deadline_s,
                startup_deadline_s=self._avatar_startup_deadline_s,
                max_session_duration_s=self._max_session_duration_s,
            )
        except Exception as exc:  # noqa: BLE001 — degrade, never propagate
            reason = _startup_failure_reason(exc)
            # Log the TYPE and our own reason, never the raw exception: an
            # aiohttp WS handshake error carries the full authenticated
            # `ws_url` in its message, which must never reach a log.
            self.logger.warning(
                "broadcast %s: avatar startup failed (%s: %s) — selecting "
                "audio_only",
                self.descriptor.broadcast_id,
                reason.value,
                type(exc).__name__,
            )
            self._avatar = None
            if self._closed:
                # A publisher failure closed us while the avatar was starting.
                # Reporting audio_only here would dress a fatal outage up as a
                # working fallback (spec AC7).
                return self.state
            await self._transition(
                BroadcastState.AUDIO_ONLY,
                reason=reason,
                output_epoch=self.output_epoch + 1,
            )
            return self.state

        if self._closed:
            # Same race, other branch: the avatar came up after teardown began.
            # Close it rather than installing an object nothing will ever free.
            avatar, self._avatar = self._avatar, None
            if avatar is not None:
                with contextlib.suppress(Exception):
                    await avatar.aclose()
            return self.state

        self._last_speech_event_at = self._clock()
        await self._transition(
            BroadcastState.AVATAR, output_epoch=self.output_epoch + 1
        )
        return self.state

    def _start_tasks(self) -> None:
        """Start the routing pump and the ownership/stop loop."""
        if self._pump_task is None:
            self._pump_task = asyncio.create_task(
                self._pump(), name=f"broadcast-pump-{self.descriptor.broadcast_id}"
            )
        if self._owner_task is None:
            self._owner_task = asyncio.create_task(
                self._owner_loop(),
                name=f"broadcast-owner-{self.descriptor.broadcast_id}",
            )

    # ── Producing ──────────────────────────────────────────────────────

    async def push_audio(self, frame: BroadcastAudioFrame) -> None:
        """Enqueue one generated PCM frame for the currently selected sink.

        The frame is *not* sent here — the pump owns every vendor call — so a
        slow vendor cannot back-pressure Nova's output loop directly.

        Args:
            frame: A fenced PCM frame.

        Raises:
            BroadcastError: If the direct sink is already the fallback and
                still cannot keep up, the affected turn is aborted with
                ``livekit_failure`` rather than accumulating stale audio.
        """
        if self._closed:
            return
        if not frame.is_current(
            owner_epoch=self.owner_epoch,
            floor_epoch=self.floor_epoch,
            output_epoch=self.output_epoch,
        ):
            self.dropped_stale_frames += 1
            return

        if self._queued_bytes + len(frame.pcm) > self._max_queued_bytes:
            await self._handle_overflow(frame)
            return

        self._queue.append((self._generation, frame))
        self._queued_bytes += len(frame.pcm)
        self._wakeup.set()

    async def _handle_overflow(self, frame: BroadcastAudioFrame) -> None:
        """Apply the bounded-queue policy (spec §2 backpressure).

        In ``avatar`` an overflow means the vendor sink is stalling, so the
        broadcast cuts over and keeps speaking.  In ``audio_only`` there is
        nowhere left to go: the turn is aborted with an explicit error rather
        than buffering audio that would be played arbitrarily late.

        Args:
            frame: The frame that would not fit.

        Raises:
            BroadcastError: In ``audio_only``.
        """
        self.dropped_overflow_frames += 1
        if self.state is BroadcastState.AVATAR:
            self.logger.warning(
                "broadcast %s: avatar sink stalled (queue full) — cutting over",
                self.descriptor.broadcast_id,
            )
            await self._cutover(BroadcastReason.AVATAR_CONTROL_LOST)
            # Best-effort re-offer to the now-direct sink under the new epoch.
            # Appended directly rather than re-entering push_audio: the cutover
            # has just refilled the queue with the retained backlog, so a
            # recursive call would see a full queue and abort the turn — the
            # opposite of what a fallback is for.  If it still does not fit, the
            # frame is dropped: spec §2 accepts "a brief gap" at the cutover
            # boundary but never unbounded accumulation.
            restamped = frame.model_copy(
                update={"output_epoch": self.output_epoch}
            )
            if self._queued_bytes + len(restamped.pcm) <= self._max_queued_bytes:
                self._queue.append((self._generation, restamped))
                self._queued_bytes += len(restamped.pcm)
                self._wakeup.set()
            return
        self._drop_queued()
        raise BroadcastError(
            BroadcastReason.LIVEKIT_FAILURE,
            message="direct audio sink cannot keep up; turn aborted",
        )

    async def _pump(self) -> None:
        """Route queued frames to the single selected sink, in order."""
        try:
            while not self._closed:
                if self._acked_generation != self._generation:
                    # The barrier is acknowledged here and nowhere else: by the
                    # time this runs, everything from the previous generation
                    # has already been discarded.
                    self._acked_generation = self._generation
                    self._gen_ack.set()
                if not self._queue:
                    # Clear-then-recheck: a producer appending between the two
                    # runs without an await in between, so no wake-up is lost.
                    self._wakeup.clear()
                    if self._queue or self._acked_generation != self._generation:
                        continue
                    await self._wakeup.wait()
                    continue

                generation, frame = self._queue.popleft()
                self._queued_bytes -= len(frame.pcm)
                # Counted as in flight until _deliver returns, so _drain (and
                # therefore finish_turn's agent.speak_end) cannot overtake it.
                self._inflight += 1
                try:
                    if generation != self._generation:
                        self.dropped_stale_frames += 1
                        continue
                    if not frame.is_current(
                        owner_epoch=self.owner_epoch,
                        floor_epoch=self.floor_epoch,
                        output_epoch=self.output_epoch,
                    ):
                        self.dropped_stale_frames += 1
                        continue
                    await self._deliver(frame)
                finally:
                    self._inflight -= 1
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — the pump must outlive one bad frame
            self.logger.exception(
                "broadcast %s: routing pump error", self.descriptor.broadcast_id
            )

    async def _deliver(self, frame: BroadcastAudioFrame) -> None:
        """Hand one frame to whichever sink the current state selects.

        Exactly one sink is ever active — clients must never receive two
        audible sources for the same speech.
        """
        if self.state is BroadcastState.AVATAR and self._avatar is not None:
            try:
                await asyncio.wait_for(
                    self._avatar.speak(frame.pcm), timeout=self._send_deadline_s
                )
                self._last_frame_sent_at = self._clock()
            except (AvatarSendTimeout, asyncio.TimeoutError):
                # The frame's fate is unknown — it may already be playing, so
                # it is ambiguous and must not be replayed.
                self.dropped_ambiguous_samples += frame.sample_count
                self.logger.warning(
                    "broadcast %s: avatar send exceeded %.2fs — cutting over",
                    self.descriptor.broadcast_id,
                    self._send_deadline_s,
                )
                await self._cutover(BroadcastReason.AVATAR_CONTROL_LOST)
            except Exception:  # noqa: BLE001
                self.dropped_ambiguous_samples += frame.sample_count
                self.logger.warning(
                    "broadcast %s: avatar send failed — cutting over",
                    self.descriptor.broadcast_id,
                    exc_info=True,
                )
                await self._cutover(BroadcastReason.AVATAR_CONTROL_LOST)
            return

        if self._publisher is not None:
            await self._publisher.capture_pcm(frame.pcm)
            self._last_frame_sent_at = self._clock()

    async def finish_turn(self, turn_id: str) -> None:
        """Complete a turn that ended on its own.

        Waits for the queue to drain, then lets the active sink finish: the
        avatar gets ``agent.speak_end``; the direct publisher gets a *bounded*
        playout wait.  This is the only place waiting for playout is correct —
        cancellation paths discard that audio instead (spec §2).

        Args:
            turn_id: The turn that completed.  Used for logging only; the
                queue is generation-fenced.
        """
        if self._closed:
            return
        await self._drain(timeout=self._send_deadline_s * 4)
        if self.state is BroadcastState.AVATAR and self._avatar is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    self._avatar.finish_turn(), timeout=self._send_deadline_s
                )
        elif self._publisher is not None:
            with contextlib.suppress(Exception):
                await self._publisher.wait_for_playout(
                    timeout_s=self._send_deadline_s * 4
                )
        self.logger.debug(
            "broadcast %s: turn %s finished", self.descriptor.broadcast_id, turn_id
        )

    async def _drain(self, *, timeout: float) -> bool:
        """Wait until the queue empties.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            ``True`` when the queue drained, ``False`` on timeout.
        """
        # Real loop time, not the injected clock: the injected clock exists to
        # make watchdog *decisions* deterministic, and a frozen fake clock here
        # would turn a bounded wait into a spin.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while (self._queue or self._inflight) and loop.time() < deadline:
            await asyncio.sleep(0.005)
        return not self._queue and not self._inflight

    # ── Interruption and handoff ───────────────────────────────────────

    def _drop_queued(self) -> int:
        """Discard every queued frame.  Returns the number dropped."""
        dropped = len(self._queue)
        self._queue.clear()
        self._queued_bytes = 0
        return dropped

    async def interrupt(self, reason: str = "barge_in") -> None:
        """Stop current speech everywhere: software queue, vendor and native.

        Clearing only the Python queue is insufficient — audio already handed
        to the avatar or to ``AudioSource`` keeps playing.  All three are
        cleared, which is why this always calls both ``avatar.interrupt()`` and
        ``publisher.flush()`` (a real ``clear_queue`` since TASK-2956).

        Args:
            reason: Short label for the log.
        """
        if self._closed:
            return
        self._generation += 1
        self._gen_ack.clear()
        dropped = self._drop_queued()
        self._wakeup.set()

        if self.state is BroadcastState.AVATAR and self._avatar is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    self._avatar.interrupt(), timeout=self._send_deadline_s
                )
        if self._publisher is not None:
            with contextlib.suppress(Exception):
                await self._publisher.flush()
        self.logger.info(
            "broadcast %s: interrupted (%s) — dropped %d queued frames",
            self.descriptor.broadcast_id,
            reason,
            dropped,
        )

    async def switch_speaker(self, new_speaker_lease_id: str, floor_epoch: int) -> None:
        """Producer half of the moderated handoff barrier.

        Everything from the previous speaker is cancelled and cleared, the
        floor epoch is advanced so late frames are rejected, and the pump must
        *acknowledge* the new generation before the caller may install the new
        speaker.  Acknowledgement is what makes "never two live sources" a
        guarantee rather than a hope.

        Args:
            new_speaker_lease_id: The lease about to receive the floor.
            floor_epoch: The new floor epoch.

        Raises:
            BroadcastError: With ``stale_floor_epoch`` if the pump does not
                acknowledge within :data:`HANDOFF_BARRIER_TIMEOUT_S`.  The
                caller must then leave the floor idle and surface a retryable
                error — never install the speaker anyway.
        """
        self.floor_epoch = floor_epoch
        await self.interrupt(reason=f"handoff->{new_speaker_lease_id}")
        try:
            await asyncio.wait_for(
                self._gen_ack.wait(), timeout=HANDOFF_BARRIER_TIMEOUT_S
            )
        except asyncio.TimeoutError as exc:
            raise BroadcastError(
                BroadcastReason.STALE_FLOOR_EPOCH,
                message=(
                    "producer did not acknowledge the handoff barrier within "
                    f"{HANDOFF_BARRIER_TIMEOUT_S}s"
                ),
            ) from exc
        self.logger.info(
            "broadcast %s: handoff barrier acknowledged for %s at floor_epoch=%d",
            self.descriptor.broadcast_id,
            new_speaker_lease_id,
            floor_epoch,
        )

    # ── Fallback ───────────────────────────────────────────────────────

    async def _cutover(self, reason: BroadcastReason) -> None:
        """Move irreversibly from avatar to direct audio.

        Only frames still queued — never handed to the vendor — are re-routed.
        A frame whose send was in flight is ambiguous and is counted in
        :attr:`dropped_ambiguous_samples` instead of being replayed.

        Args:
            reason: Sanitized reason recorded on the descriptor.
        """
        async with self._cutover_lock:
            if self.state is not BroadcastState.AVATAR:
                return  # One-way and idempotent.

            retained = [
                frame
                for generation, frame in self._queue
                if generation == self._generation
            ]
            self._drop_queued()

            self.output_epoch += 1
            self.state = BroadcastState.AUDIO_ONLY
            self.failure_reason = reason

            avatar, self._avatar = self._avatar, None
            if avatar is not None:
                with contextlib.suppress(Exception):
                    await avatar.aclose()
            with contextlib.suppress(Exception):
                await self.room_manager.remove_participant(
                    self.room_name, self.avatar_identity
                )

            # Re-stamp with the new output epoch, otherwise the pump would
            # reject the very frames we are trying to save.
            for frame in retained:
                self._queue.append(
                    (
                        self._generation,
                        frame.model_copy(update={"output_epoch": self.output_epoch}),
                    )
                )
                self._queued_bytes += len(frame.pcm)
            self.forwarded_on_cutover += len(retained)
            if retained:
                self._wakeup.set()

            await self._transition(
                BroadcastState.AUDIO_ONLY,
                reason=reason,
                output_epoch=self.output_epoch,
            )
            self.logger.warning(
                "broadcast %s: cut over to audio_only (%s) — forwarded %d frames, "
                "dropped %d ambiguous samples",
                self.descriptor.broadcast_id,
                reason.value,
                len(retained),
                self.dropped_ambiguous_samples,
            )

    async def _on_avatar_event(self, event: Dict[str, Any]) -> None:
        """Observe LITE control events: progress heartbeat and fatal errors.

        Event *names* are not hard-coded — the TASK-2950 live gate did not run,
        so this matches on substrings and records what it saw.
        """
        event_type = str(event.get("type", "")).lower()
        if "speak" in event_type or "speaking" in event_type:
            self._last_speech_event_at = self._clock()
        if "error" in event_type or "fail" in event_type:
            self.logger.warning(
                "broadcast %s: vendor fatal event %r",
                self.descriptor.broadcast_id,
                event.get("type"),
            )
            await self._cutover(BroadcastReason.AVATAR_CONTROL_LOST)

    async def _on_avatar_close(self, reason: str) -> None:
        """The avatar control socket dropped — a fallback trigger, not a retry."""
        self.logger.warning(
            "broadcast %s: avatar control socket closed (%s)",
            self.descriptor.broadcast_id,
            reason,
        )
        await self._cutover(BroadcastReason.AVATAR_CONTROL_LOST)

    async def on_participant_disconnected(self, identity: str) -> None:
        """Hook for room-level participant loss.

        Wired by the service layer from LiveKit participant events or from
        reconciliation.  Only the avatar's own identity triggers a cutover.

        Args:
            identity: The participant that left.
        """
        if identity == self.avatar_identity:
            await self._cutover(BroadcastReason.AVATAR_TRACK_LOST)

    async def _on_publisher_failure(self, reason: str) -> None:
        """The direct publisher failed — there is no further sink to fall to."""
        self.logger.error(
            "broadcast %s: direct publisher failed (%s)",
            self.descriptor.broadcast_id,
            reason,
        )
        await self._abort(BroadcastReason.LIVEKIT_FAILURE)

    def _check_speech_watchdog(self) -> bool:
        """Whether the avatar stopped making progress while speech was expected.

        Idle silence is *not* a failure (spec §2), so this only fires when
        frames were recently sent and no speaking event followed.

        Returns:
            ``True`` when a cutover is warranted.
        """
        if self.state is not BroadcastState.AVATAR:
            return False
        if self._last_frame_sent_at is None:
            return False
        now = self._clock()
        if (now - self._last_frame_sent_at) > self._speech_watchdog_s:
            return False  # Nothing was sent recently: this is idle, not stalled.
        last_event = self._last_speech_event_at or self._last_frame_sent_at
        return (now - last_event) > self._speech_watchdog_s

    # ── Ownership, stop, teardown ──────────────────────────────────────

    async def _owner_loop(self) -> None:
        """Renew the ownership lease, poll the stop flag and run the watchdog."""
        last_renew = self._clock()
        try:
            while not self._closed:
                await asyncio.sleep(STOP_POLL_S)
                if self._closed:
                    return

                now = self._clock()
                if (now - last_renew) >= OWNER_RENEW_S:
                    last_renew = now
                    if not await self._renew_owner():
                        return

                if await self._stop_requested():
                    self.logger.info(
                        "broadcast %s: stop requested — tearing down",
                        self.descriptor.broadcast_id,
                    )
                    await self.aclose(
                        final_state=BroadcastState.ENDED,
                        reason=BroadcastReason.STOPPED_BY_MODERATOR,
                    )
                    return

                if self._check_speech_watchdog():
                    self.logger.warning(
                        "broadcast %s: no vendor speech progress within %.1fs",
                        self.descriptor.broadcast_id,
                        self._speech_watchdog_s,
                    )
                    await self._cutover(BroadcastReason.AVATAR_TRACK_LOST)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "broadcast %s: owner loop error", self.descriptor.broadcast_id
            )

    async def _renew_owner(self) -> bool:
        """Extend the ownership lease, stopping the broadcast if fenced.

        Returns:
            ``True`` while ownership is retained.
        """
        try:
            renewed = await self.registry.renew_owner(
                self.descriptor.tenant_id,
                self.descriptor.broadcast_id,
                self.worker_id,
                self.owner_epoch,
            )
        except Exception:  # noqa: BLE001 — treat an unreachable store as a loss
            self.logger.warning(
                "broadcast %s: owner renewal errored", self.descriptor.broadcast_id,
                exc_info=True,
            )
            renewed = False
        if renewed:
            return True
        # Fail closed: stop publishing BEFORE the lease could expire elsewhere,
        # so two producers can never overlap.
        self.logger.error(
            "broadcast %s: lost ownership — stopping publication",
            self.descriptor.broadcast_id,
        )
        await self.aclose(
            final_state=BroadcastState.FAILED, reason=BroadcastReason.OWNER_LOST
        )
        return False

    async def _stop_requested(self) -> bool:
        """Poll the durable stop flag, tolerating a store blip."""
        try:
            return await self.registry.stop_requested(
                self.descriptor.tenant_id, self.descriptor.broadcast_id
            )
        except Exception:  # noqa: BLE001 — a blip must not end the broadcast
            self.logger.debug(
                "broadcast %s: stop poll failed", self.descriptor.broadcast_id,
                exc_info=True,
            )
            return False

    async def _abort(self, reason: BroadcastReason) -> None:
        """Fatal path: tear down and mark ``failed``, never ``audio_only``."""
        await self.aclose(final_state=BroadcastState.FAILED, reason=reason)

    async def aclose(
        self,
        *,
        final_state: BroadcastState = BroadcastState.ENDED,
        reason: Optional[BroadcastReason] = None,
        delete_room: bool = True,
    ) -> None:
        """Release every resource.  Idempotent and cancellation-safe.

        Safe to call at any startup stage — each step is independently guarded,
        so a session cancelled between the publisher and the avatar still
        closes what it managed to open.

        Args:
            final_state: Terminal state to record.
            reason: Sanitized reason for that state.
            delete_room: Whether to delete the LiveKit room.
        """
        async with self._closing:
            if self._teardown_done:
                return
            # `_closed` stops new audio immediately; `_teardown_done` is only
            # set once the awaited cleanup below actually finished, so a
            # cancellation part-way through does not make a retry a no-op and
            # strand the avatar, publisher and room.
            self._closed = True
            self._wakeup.set()

        for task in (self._pump_task, self._owner_task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._pump_task = None
        self._owner_task = None
        self._drop_queued()

        avatar, self._avatar = self._avatar, None
        if avatar is not None:
            with contextlib.suppress(Exception):
                await avatar.interrupt()
            with contextlib.suppress(Exception):
                await avatar.aclose()

        publisher, self._publisher = self._publisher, None
        if publisher is not None:
            with contextlib.suppress(Exception):
                await publisher.aclose()

        if delete_room:
            with contextlib.suppress(Exception):
                await self.room_manager.delete_room(self.room_name)

        self.state = final_state
        if reason is not None:
            self.failure_reason = reason
        self._teardown_done = True
        with contextlib.suppress(Exception):
            await self.registry.transition(
                self.descriptor.tenant_id,
                self.descriptor.broadcast_id,
                final_state,
                reason=reason,
                expected_owner_epoch=self.owner_epoch,
            )
        self.logger.info(
            "broadcast %s: closed state=%s reason=%s (stale=%d overflow=%d "
            "ambiguous_samples=%d forwarded=%d)",
            self.descriptor.broadcast_id,
            final_state.value,
            reason.value if reason else "-",
            self.dropped_stale_frames,
            self.dropped_overflow_frames,
            self.dropped_ambiguous_samples,
            self.forwarded_on_cutover,
        )


def _startup_failure_reason(exc: BaseException) -> BroadcastReason:
    """Classify an avatar startup failure into a sanitized reason code.

    Args:
        exc: The exception raised during avatar startup.

    Returns:
        ``avatar_startup_timeout`` for a deadline, ``avatar_control_lost``
        otherwise.
    """
    if isinstance(exc, (AvatarStartupTimeout, asyncio.TimeoutError)):
        return BroadcastReason.AVATAR_STARTUP_TIMEOUT
    return BroadcastReason.AVATAR_CONTROL_LOST


__all__ = [
    "DIRECT_TRACK_NAME",
    "ROOM_CAPACITY",
    "STOP_POLL_S",
    "BroadcastSession",
]
