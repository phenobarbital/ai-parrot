"""Central engine for human-in-the-loop interactions."""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional
from uuid import uuid4

from navconfig.logging import logging

from .actions.notify import NotifyAction
from .actions.ticket import TicketAction
from .channels.base import ESCALATE_OPTION_KEY, HumanChannel
from .escalation_intent import RejectIntentDetector
from .events import (
    HitlChainExhaustedEvent,
    HitlTierActionExecutedEvent,
    HitlTierActionFailedEvent,
    HitlTierAdvancedEvent,
    HitlTierEnteredEvent,
)
from .models import (
    ConsensusMode,
    EscalationActionType,
    EscalationPolicy,
    HumanInteraction,
    HumanResponse,
    InteractionResult,
    InteractionStatus,
    Severity,
    TimeoutAction,
)

# Maximum allowed TTL for multi-tier chains (24h in seconds)
_MAX_REDIS_TTL = 86400


def _stable_key(value: Any) -> str:
    """Produce a stable hashable key for consensus vote counting.

    Compared to ``str(value)``, this is deterministic for dicts/lists
    (sorted keys) and preserves semantic identity.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


class HumanInteractionManager:
    """Orchestrates the full lifecycle of human interactions.

    Responsibilities:
    - Persist pending interactions in Redis
    - Dispatch questions to the correct channel
    - Receive and validate responses
    - Apply consensus logic
    - Handle timeouts and escalation
    - Resolve the caller's future (long-polling) or trigger rehydration (suspend/resume)
    """

    # Response types that are compatible (channel may translate)
    _COMPATIBLE_TYPES = {
        "form": {"form", "free_text"},        # Telegram sends form as free_text
        "poll": {"poll", "single_choice"},     # CLI renders polls as single_choice
        "free_text": {"free_text"},
        "approval": {"approval"},
        "single_choice": {"single_choice"},
        "multi_choice": {"multi_choice"},
    }

    def __init__(
        self,
        channels: Optional[Dict[str, HumanChannel]] = None,
        redis_url: Optional[str] = None,
        reject_detector: Optional[RejectIntentDetector] = None,
        on_event: Optional[Callable[[str, Any], Awaitable[None]]] = None,
    ) -> None:
        self.channels: Dict[str, HumanChannel] = channels or {}
        self._redis_url = redis_url
        self._redis = None
        self._redis_lock = asyncio.Lock()
        self._pending_futures: Dict[str, asyncio.Future] = {}
        self._timeout_tasks: Dict[str, asyncio.Task] = {}
        self.logger = logging.getLogger("parrot.human.manager")
        self._actions: Dict[EscalationActionType, Any] = {
            EscalationActionType.TICKET: TicketAction(),
            EscalationActionType.NOTIFY: NotifyAction(),
        }
        self._policies: Dict[str, EscalationPolicy] = {}
        self._reject_detector: Optional[RejectIntentDetector] = reject_detector
        self._on_event: Optional[Callable[[str, Any], Awaitable[None]]] = on_event

    # ------------------------------------------------------------------
    # Public registration API
    # ------------------------------------------------------------------

    def register_policy(self, policy: EscalationPolicy) -> None:
        """Register an escalation policy by its ``policy_id``."""
        self._policies[policy.policy_id] = policy

    def set_action(
        self, action_type: EscalationActionType, action: Any
    ) -> None:
        """Set (or replace) the handler for *action_type*."""
        self._actions[action_type] = action

    # ------------------------------------------------------------------
    # Event emission helpers
    # ------------------------------------------------------------------

    async def _emit(self, event_name: str, payload: Any) -> None:
        """Emit a structured event to the registered subscriber.

        Emission is best-effort: subscriber exceptions are caught and
        logged so the manager's control flow is never interrupted.

        Args:
            event_name: Dot-namespaced event identifier (e.g. ``"hitl.tier.entered"``).
            payload: A Pydantic event model from :mod:`parrot.human.events`.
        """
        if self._on_event is None:
            return
        try:
            await self._on_event(event_name, payload)
        except Exception:
            self.logger.exception(
                "HITL event subscriber raised for event %r", event_name
            )

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    async def _get_redis(self):
        """Lazy-init Redis connection (concurrency-safe)."""
        if self._redis is not None:
            return self._redis
        async with self._redis_lock:
            if self._redis is not None:
                return self._redis
            import redis.asyncio as aioredis

            url = self._redis_url
            if url is None:
                try:
                    from parrot.conf import REDIS_URL
                    url = REDIS_URL
                except ImportError:
                    url = "redis://localhost:6379/1"
            self._redis = aioredis.from_url(url, decode_responses=True)
        return self._redis

    def _compute_ttl(self, interaction: HumanInteraction) -> int:
        """Compute a Redis TTL that covers the full multi-tier chain.

        For single-hop interactions, this is ``int(interaction.timeout) + 60``.
        For policy-bound interactions, it is at least the sum of all tier
        timeouts plus a 60-second buffer, capped at 24h.

        Args:
            interaction: The interaction to compute TTL for.

        Returns:
            TTL in seconds (integer), capped at 24h.
        """
        base_ttl = int(interaction.timeout) + 60
        if interaction.policy and interaction.policy.tiers:
            tier_total = int(sum(t.timeout for t in interaction.policy.tiers)) + 60
            ttl = max(base_ttl, tier_total)
        else:
            ttl = base_ttl
        return min(ttl, _MAX_REDIS_TTL)

    async def _persist_interaction(self, interaction: HumanInteraction) -> None:
        """Store an interaction in Redis with TTL covering the full multi-tier chain."""
        redis = await self._get_redis()
        key = f"hitl:interaction:{interaction.interaction_id}"
        ttl = self._compute_ttl(interaction)
        await redis.setex(key, ttl, interaction.model_dump_json())

    async def _load_interaction(
        self, interaction_id: str
    ) -> Optional[HumanInteraction]:
        """Load an interaction from Redis by ID."""
        redis = await self._get_redis()
        raw = await redis.get(f"hitl:interaction:{interaction_id}")
        if raw is None:
            return None
        return HumanInteraction.model_validate_json(raw)

    async def _update_status(self, interaction: HumanInteraction) -> None:
        """Overwrite the persisted interaction with updated status."""
        await self._persist_interaction(interaction)

    async def _persist_responses(
        self, interaction_id: str, responses: List[HumanResponse]
    ) -> None:
        """Store accumulated responses in Redis."""
        redis = await self._get_redis()
        key = f"hitl:responses:{interaction_id}"
        data = json.dumps([r.model_dump(mode="json") for r in responses])
        await redis.setex(key, 86400, data)

    async def _load_responses(
        self, interaction_id: str
    ) -> List[HumanResponse]:
        """Load accumulated responses from Redis.

        Ensures multi-human consensus survives process restarts.
        """
        redis = await self._get_redis()
        raw = await redis.get(f"hitl:responses:{interaction_id}")
        if raw is None:
            return []
        try:
            items = json.loads(raw)
            return [HumanResponse.model_validate(r) for r in items]
        except Exception:
            self.logger.exception(
                "Failed to deserialize responses for %s", interaction_id
            )
            return []

    async def _persist_result(self, result: InteractionResult) -> None:
        """Store the final result in Redis (24h TTL)."""
        redis = await self._get_redis()
        key = f"hitl:result:{result.interaction_id}"
        await redis.setex(key, 86400, result.model_dump_json())

    # ------------------------------------------------------------------
    # Ownership validation
    # ------------------------------------------------------------------

    async def is_valid_respondent(
        self, interaction_id: str, respondent: str
    ) -> bool:
        """Check whether *respondent* is an intended recipient of the interaction.

        Fails closed: returns ``False`` when the interaction cannot be loaded
        from Redis, so a missing 404 check upstream cannot turn into an
        authorisation bypass. Returns ``True`` only when the interaction exists
        AND (target_humans is empty (open broadcast) OR respondent appears in
        target_humans).

        Args:
            interaction_id: UUID of the pending interaction.
            respondent: User identifier extracted from the authenticated session.

        Returns:
            ``True`` if the respondent is authorised, ``False`` otherwise.
        """
        interaction = await self._load_interaction(interaction_id)
        if interaction is None:
            return False
        if not interaction.target_humans:
            # No specific targets: open to any authenticated user.
            return True
        return respondent in interaction.target_humans

    # ------------------------------------------------------------------
    # Channel registration
    # ------------------------------------------------------------------

    def register_channel(self, name: str, channel: HumanChannel) -> None:
        """Register a communication channel."""
        self.channels[name] = channel

    async def startup(self) -> None:
        """Register response + cancel handlers on all channels."""
        for name, channel in self.channels.items():
            await channel.register_response_handler(self.receive_response)
            await channel.register_cancel_handler(self.cancel_pending)
            self.logger.info(
                "Registered response + cancel handlers for channel: %s", name
            )

    # ------------------------------------------------------------------
    # Public API: long-polling mode
    # ------------------------------------------------------------------

    async def _terminate_no_applicable_tier(
        self, interaction: HumanInteraction
    ) -> InteractionResult:
        """Resolve an interaction whose policy yielded no applicable starting tier.

        ``_resolve_interaction_policy`` leaves ``current_tier_level`` at 0 when
        ``select_starting_tier`` returns ``None`` (every tier blocked by its
        severity floor / business-hours window). Both the blocking and the
        suspend entry points funnel through here so the behaviour is identical:
        emit ``hitl.chain.exhausted``, persist a terminal TIMEOUT result, and
        return it without dispatching to any channel.

        Returns:
            The persisted terminal :class:`InteractionResult` (status TIMEOUT).
        """
        self.logger.warning(
            "Interaction %s has policy %s but no applicable starting tier; "
            "terminating immediately.",
            interaction.interaction_id,
            interaction.policy_id,
        )
        # Emit hitl.chain.exhausted when no applicable starting tier is found
        # (Issue 6).
        await self._emit(
            "hitl.chain.exhausted",
            HitlChainExhaustedEvent(
                interaction_id=interaction.interaction_id,
                policy_id=interaction.policy_id or "",
            ),
        )
        result = InteractionResult(
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.TIMEOUT,
            timed_out=True,
        )
        await self._persist_result(result)
        return result

    async def request_human_input(
        self,
        interaction: HumanInteraction,
        channel: str = "telegram",
    ) -> InteractionResult:
        """Send an interaction and block until a result is available.

        This is the synchronous (long-polling) entry point used by
        ``HumanTool`` and ``HumanDecisionNode`` when the human is
        expected to respond within the timeout window.

        IMPORTANT: The future must be registered BEFORE dispatching to
        the channel.  Synchronous channels (e.g. CLIHumanChannel) block
        on user input inside ``send_interaction`` and fire the response
        callback inline — so the future must already exist for
        ``receive_response`` to resolve it.
        """
        # 1. Resolve Policy (sets starting tier via select_starting_tier)
        await self._resolve_interaction_policy(interaction)

        # 1b. If policy set but no applicable starting tier, terminate immediately.
        if interaction.policy and interaction.current_tier_level == 0:
            return await self._terminate_no_applicable_tier(interaction)

        # 2. Persist
        await self._persist_interaction(interaction)

        # 3. Create awaitable future BEFORE dispatch
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_futures[interaction.interaction_id] = future

        # 4. Schedule timeout handler
        timeout_task = asyncio.create_task(
            self._handle_timeout(interaction, channel)
        )
        self._timeout_tasks[interaction.interaction_id] = timeout_task

        # 5. Dispatch to channel (may resolve the future synchronously
        #    for CLI-style channels)
        await self._dispatch_to_channel(interaction, channel)

        # 6. Wait for resolution
        try:
            result: InteractionResult = await future
            timeout_task.cancel()
            return result
        except asyncio.CancelledError:
            timeout_task.cancel()
            return InteractionResult(
                interaction_id=interaction.interaction_id,
                status=InteractionStatus.CANCELLED,
            )
        finally:
            self._pending_futures.pop(interaction.interaction_id, None)
            self._timeout_tasks.pop(interaction.interaction_id, None)

    async def _resolve_interaction_policy(
        self, interaction: HumanInteraction
    ) -> None:
        """Resolve policy_id to a policy object and seed starting tier.

        Uses ``select_starting_tier`` to pick the first applicable tier
        based on ``interaction.severity`` and the current time. If no tier
        is applicable (all blocked by severity floor / business hours),
        the interaction's ``current_tier_level`` is left at 0 — the
        caller (``request_human_input``) will detect this and terminate.
        """
        if not interaction.policy_id:
            return
        policy = self._policies.get(interaction.policy_id)
        if not policy:
            self.logger.warning(
                "Policy %s not registered for interaction %s",
                interaction.policy_id,
                interaction.interaction_id,
            )
            return
        interaction.policy = policy

        if interaction.current_tier_level == 0 and policy.tiers:
            now = datetime.now(timezone.utc)
            severity = getattr(interaction, "severity", Severity.NORMAL)
            starting_tier = policy.select_starting_tier(severity, now)
            if starting_tier is None:
                self.logger.info(
                    "Policy %s: no tier applicable at start for severity=%s; "
                    "interaction %s will terminate immediately.",
                    interaction.policy_id,
                    severity,
                    interaction.interaction_id,
                )
                # Leave current_tier_level at 0 — caller handles this.
                return
            interaction.current_tier_level = starting_tier.level
            # Adjust targets/timeout from starting tier
            interaction.target_humans = (
                starting_tier.target_humans or interaction.target_humans
            )
            interaction.timeout = starting_tier.timeout

    async def _dispatch_to_channel(
        self, interaction: HumanInteraction, channel: str
    ) -> None:
        """Send the interaction through the specified channel."""
        if channel not in self.channels:
            self.logger.warning(
                "Channel '%s' not registered; interaction %s was persisted "
                "but not dispatched.",
                channel,
                interaction.interaction_id,
            )
            return

        # Record the originating channel on the interaction so advance_chain
        # can target the same channel when re-escalating (Issue 7).
        interaction.channel = channel

        channel_impl = self.channels[channel]
        delivered_count = 0
        failed: List[str] = []
        for human_id in interaction.target_humans:
            delivered = await channel_impl.send_interaction(
                interaction, human_id
            )
            if delivered:
                delivered_count += 1
                interaction.status = InteractionStatus.DELIVERED
            else:
                failed.append(human_id)

        if interaction.target_humans and delivered_count == 0:
            self.logger.warning(
                "Interaction %s not delivered to any target on channel '%s' "
                "(targets=%s)",
                interaction.interaction_id,
                channel,
                interaction.target_humans,
            )
        elif failed:
            self.logger.warning(
                "Interaction %s: channel '%s' failed to deliver to %s",
                interaction.interaction_id,
                channel,
                failed,
            )
        await self._update_status(interaction)

    # ------------------------------------------------------------------
    # Public API: hybrid mode (hot wait + suspend)
    # ------------------------------------------------------------------

    async def register_and_send(
        self,
        interaction: HumanInteraction,
        channel: str = "telegram",
    ) -> asyncio.Future:
        """Register an interaction and return a Future.

        Used by the HOT_THEN_SUSPEND strategy in HumanTool:
        - The tool awaits the future with a short timeout (hot_wait)
        - If the human responds quickly, the future resolves
        - If not, the tool raises AgentSuspendException
        - The future stays registered so receive_response can still
          resolve it (but if the agent is already suspended,
          rehydration kicks in instead)
        """
        await self._resolve_interaction_policy(interaction)
        await self._persist_interaction(interaction)
        await self._dispatch_to_channel(interaction, channel)

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_futures[interaction.interaction_id] = future

        return future

    # ------------------------------------------------------------------
    # Public API: suspend/resume mode
    # ------------------------------------------------------------------

    async def request_human_input_async(
        self,
        interaction: HumanInteraction,
        channel: str = "telegram",
        schedule_timeout: bool = True,
    ) -> str:
        """Non-blocking variant that returns the interaction_id immediately.

        The caller serialises its own state and resumes when the result
        appears in Redis (via ``get_result`` or a pub/sub listener).

        Args:
            interaction: The :class:`HumanInteraction` to register.
            channel: Channel name to dispatch the interaction on.
            schedule_timeout: When ``False`` the in-process
                :meth:`_handle_timeout` task is **not** created.  Pass
                ``False`` from the SUSPEND path (FEAT-204): the HTTP
                handler returns immediately after persisting state, so
                there is no running event loop to host a meaningful
                timeout task.  The interaction TTL in Redis provides the
                only expiry guarantee in that mode.
        """
        await self._resolve_interaction_policy(interaction)

        # If policy set but no applicable starting tier, terminate immediately:
        # persist the terminal TIMEOUT result and return the id so the caller
        # resolves it on its next get_result poll (no dispatch, no timeout task).
        if interaction.policy and interaction.current_tier_level == 0:
            await self._terminate_no_applicable_tier(interaction)
            return interaction.interaction_id

        await self._persist_interaction(interaction)

        if channel in self.channels:
            channel_impl = self.channels[channel]
            for human_id in interaction.target_humans:
                await channel_impl.send_interaction(interaction, human_id)

        # Store callback metadata for rehydration
        redis = await self._get_redis()
        callback_data = json.dumps({
            "source_agent": interaction.source_agent,
            "source_flow": interaction.source_flow,
            "source_node": interaction.source_node,
        })
        ttl = int(interaction.timeout)
        await redis.setex(
            f"hitl:callback:{interaction.interaction_id}",
            ttl,
            callback_data,
        )

        if schedule_timeout:
            # Schedule timeout — tracked so receive_response can cancel it.
            timeout_task = asyncio.create_task(
                self._handle_timeout(interaction, channel)
            )
            self._timeout_tasks[interaction.interaction_id] = timeout_task

        return interaction.interaction_id

    async def get_result(
        self, interaction_id: str
    ) -> Optional[InteractionResult]:
        """Poll Redis for a completed interaction result."""
        redis = await self._get_redis()
        raw = await redis.get(f"hitl:result:{interaction_id}")
        if raw is None:
            return None
        return InteractionResult.model_validate_json(raw)

    async def advance_chain(
        self,
        interaction_id: str,
        cause: Literal["timeout", "reject", "business_hours_off", "action_failed"] = "timeout",
    ) -> None:
        """Public entry point for advancing a tiered escalation chain.

        Called by channels (reject button), the web HITL handler, and tests.
        Loads the interaction from Redis, cancels any running timeout task,
        and delegates to ``_escalate_to_next_tier`` with the given *cause*.

        If the interaction is not found (expired or unknown id), the call
        is silently ignored.

        Args:
            interaction_id: UUID of the interaction to advance.
            cause: Reason for advancing — used for logging and future event
                emission.  One of ``"timeout"``, ``"reject"``,
                ``"business_hours_off"``, ``"action_failed"``.
        """
        interaction = await self._load_interaction(interaction_id)
        if interaction is None:
            self.logger.debug(
                "advance_chain: unknown or expired interaction %s", interaction_id
            )
            return

        # Already resolved — nothing to advance.
        if await self.get_result(interaction_id) is not None:
            self.logger.debug(
                "advance_chain: interaction %s already resolved", interaction_id
            )
            return

        # Derive the channel from the originating channel stored on the interaction
        # (Issue 7); fall back to first registered channel if not set.
        channel = interaction.channel or "telegram"
        if not interaction.channel and self.channels:
            channel = next(iter(self.channels))

        # Cancel any existing timeout task so it doesn't race us.
        timeout_task = self._timeout_tasks.pop(interaction_id, None)
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()

        self.logger.info(
            "advance_chain: advancing interaction %s (cause=%s)",
            interaction_id,
            cause,
        )
        # NOTE: hitl.tier.advanced is emitted inside _escalate_to_next_tier
        # after confirming the tier is applicable (not skipped). Emitting here
        # would produce a duplicate event (Issue 8).
        await self._escalate_to_next_tier(interaction, channel, cause=cause)

    # ------------------------------------------------------------------
    # Response ingestion (called by channels)
    # ------------------------------------------------------------------

    async def receive_response(self, response: HumanResponse) -> None:
        """Process an incoming human response.

        1. Validate against interaction schema
        2. Accumulate (load from Redis for crash safety)
        3. Evaluate consensus
        4. Resolve future or persist result for rehydration
        """
        interaction = await self._load_interaction(response.interaction_id)
        if interaction is None:
            self.logger.debug(
                "No interaction found for id=%s (expired?)",
                response.interaction_id,
            )
            return

        # --- Escalate-sentinel interception (TASK-1279) ---
        # Check BEFORE type validation: the escalate sentinel may arrive as
        # FREE_TEXT even when the interaction is APPROVAL (Teams sends the
        # Escalate button as free_text).  It is a control signal, not a typed
        # response, so it must bypass compatibility checks.
        if (
            interaction.policy is not None
            and isinstance(response.value, str)
            and response.value == ESCALATE_OPTION_KEY
        ):
            self.logger.info(
                "Escalate button pressed for interaction %s; "
                "advancing chain (cause=reject).",
                response.interaction_id,
            )
            await self.advance_chain(response.interaction_id, cause="reject")
            return

        # Validate response type is compatible
        if not self._validate_response(interaction, response):
            self.logger.warning(
                "Incompatible response for interaction %s: "
                "expected %s, got %s",
                response.interaction_id,
                interaction.interaction_type,
                response.response_type,
            )
            return

        # --- Escalation-intent interception (TASK-1278) ---
        # If the interaction is policy-bound and the user typed something
        # that looks like "I need a human", advance the chain instead of
        # accumulating the response.
        if (
            interaction.policy is not None
            and self._reject_detector is not None
            and interaction.interaction_type.value == "free_text"
            and isinstance(response.value, str)
            and await self._reject_detector.is_escalation_intent(response.value)
        ):
            self.logger.info(
                "Escalation intent detected in response for interaction %s; "
                "advancing chain (cause=reject).",
                response.interaction_id,
            )
            await self.advance_chain(response.interaction_id, cause="reject")
            return

        # Accumulate: load from Redis (crash-safe), then append
        acc = await self._load_responses(interaction.interaction_id)

        # Deduplicate: reject if this respondent already submitted
        existing_respondents = {r.respondent for r in acc}
        if response.respondent in existing_respondents:
            self.logger.warning(
                "Duplicate response from '%s' for interaction %s — ignored.",
                response.respondent,
                response.interaction_id,
            )
            return

        acc.append(response)
        await self._persist_responses(interaction.interaction_id, acc)

        # Evaluate consensus
        reached, consolidated = self._evaluate_consensus(interaction, acc)

        if not reached:
            interaction.status = InteractionStatus.PARTIAL
            await self._update_status(interaction)
            return

        # Build result
        result = InteractionResult(
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.COMPLETED,
            responses=acc,
            consolidated_value=consolidated,
        )

        await self._persist_result(result)

        # Cancel timeout task in both modes — suspend/resume also schedules one.
        timeout_task = self._timeout_tasks.pop(interaction.interaction_id, None)
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()

        # Resolve in-memory future (long-polling / hot-wait mode).
        future = self._pending_futures.pop(interaction.interaction_id, None)
        if future is not None and not future.done():
            future.set_result(result)
        else:
            # Suspend/resume mode — publish event for rehydration.
            await self._trigger_rehydration(interaction, result)

    # ------------------------------------------------------------------
    # User-initiated cancellation
    # ------------------------------------------------------------------

    async def cancel_pending(
        self,
        interaction_id: str,
        reason: str = "user_cancelled",
    ) -> bool:
        """Resolve a pending interaction with CANCELLED status.

        Intended to be invoked by a channel when the human cancels the
        interaction (e.g. ``/cancel`` command on Telegram, ✕ Cancel button).
        Cancels the timeout task, resolves the pending Future so the
        waiting ``ask_human`` call unblocks, persists the result, and —
        in suspend/resume mode — publishes a rehydration event.

        Args:
            interaction_id: Id of the interaction to cancel.
            reason: Short marker stored in the result metadata.

        Returns:
            True if a pending interaction was found and cancelled,
            False if there was nothing to cancel (already resolved,
            expired, or unknown id).
        """
        interaction = await self._load_interaction(interaction_id)
        result = InteractionResult(
            interaction_id=interaction_id,
            status=InteractionStatus.CANCELLED,
        )

        # Cancel the timeout task first so it can't race us.
        timeout_task = self._timeout_tasks.pop(interaction_id, None)
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()

        # Hot-wait path: resolve the future so ask_human returns.
        future = self._pending_futures.pop(interaction_id, None)
        if future is not None and not future.done():
            future.set_result(result)
            await self._persist_result(result)
            self.logger.info(
                "Interaction %s cancelled (reason=%s)", interaction_id, reason
            )
            return True

        # Suspend/resume path: persist result + publish event.
        if interaction is not None:
            await self._persist_result(result)
            await self._trigger_rehydration(interaction, result)
            self.logger.info(
                "Interaction %s cancelled (suspend/resume, reason=%s)",
                interaction_id,
                reason,
            )
            return True

        return False

    # ------------------------------------------------------------------
    # Consensus
    # ------------------------------------------------------------------

    @classmethod
    def _validate_response(
        cls,
        interaction: HumanInteraction,
        response: HumanResponse,
    ) -> bool:
        """Check that the response type is compatible with the interaction.

        Channels may translate interaction types (e.g. Telegram renders
        forms as free_text), so we allow compatible type pairs.
        """
        expected = interaction.interaction_type.value
        actual = response.response_type.value
        compatible = cls._COMPATIBLE_TYPES.get(expected, {expected})
        return actual in compatible

    @staticmethod
    def _evaluate_consensus(
        interaction: HumanInteraction,
        responses: List[HumanResponse],
    ) -> tuple[bool, Any]:
        """Determine whether consensus has been reached."""
        total_expected = max(len(interaction.target_humans), 1)
        total_received = len(responses)
        mode = interaction.consensus_mode

        if mode == ConsensusMode.FIRST_RESPONSE:
            return True, responses[0].value

        if mode == ConsensusMode.ALL_REQUIRED:
            if total_received < total_expected:
                return False, None
            values = [r.value for r in responses]
            unique = set(_stable_key(v) for v in values)
            if len(unique) == 1:
                return True, values[0]
            return True, {"conflict": True, "responses": values}

        if mode == ConsensusMode.MAJORITY:
            threshold = total_expected // 2 + 1
            if total_received < threshold:
                return False, None
            winner_value, count = HumanInteractionManager._tally(responses)
            if count >= threshold:
                return True, winner_value
            # Below threshold — wait unless everyone has voted, in which
            # case it is a tie that will never break: emit a conflict result.
            if total_received >= total_expected:
                return True, {
                    "conflict": True,
                    "responses": [r.value for r in responses],
                }
            return False, None

        if mode == ConsensusMode.QUORUM:
            # At least half responded, and majority among those.
            if total_received < max(total_expected // 2, 1):
                return False, None
            winner_value, count = HumanInteractionManager._tally(responses)
            if count > total_received // 2:
                return True, winner_value
            # Strict-majority tie. Keep waiting if more votes can arrive,
            # else surface the deadlock as a conflict result.
            if total_received >= total_expected:
                return True, {
                    "conflict": True,
                    "responses": [r.value for r in responses],
                }
            return False, None

        return False, None

    @staticmethod
    def _tally(responses: List[HumanResponse]) -> tuple[Any, int]:
        """Return (winner_value, vote_count) for the most-voted response."""
        key_to_value: Dict[str, Any] = {}
        vote_keys: List[str] = []
        for r in responses:
            k = _stable_key(r.value)
            key_to_value[k] = r.value
            vote_keys.append(k)
        winner_key, count = Counter(vote_keys).most_common(1)[0]
        return key_to_value[winner_key], count

    # ------------------------------------------------------------------
    # Timeout & escalation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_timeout_result(
        interaction: HumanInteraction,
    ) -> InteractionResult:
        """Build an InteractionResult for a timed-out interaction."""
        if interaction.timeout_action == TimeoutAction.DEFAULT:
            return InteractionResult(
                interaction_id=interaction.interaction_id,
                status=InteractionStatus.COMPLETED,
                consolidated_value=interaction.default_response,
                timed_out=True,
            )
        return InteractionResult(
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.TIMEOUT,
            timed_out=True,
        )

    async def _handle_timeout(
        self, interaction: HumanInteraction, channel: str
    ) -> None:
        """Wait for the timeout period, then apply the configured action.

        Works for both long-polling and suspend/resume modes — the action
        helpers (``_escalate_to_next_tier``, ``_retry``, ``_finish_with_timeout``)
        fall back to ``_trigger_rehydration`` when no future is registered.
        """
        await asyncio.sleep(interaction.timeout)

        # If a result has already been persisted, nothing to do.
        if await self.get_result(interaction.interaction_id) is not None:
            return

        action = interaction.timeout_action

        if action == TimeoutAction.ESCALATE:
            if interaction.policy:
                await self._emit(
                    "hitl.tier.advanced",
                    HitlTierAdvancedEvent(
                        interaction_id=interaction.interaction_id,
                        policy_id=interaction.policy_id,
                        from_level=interaction.current_tier_level,
                        to_level=interaction.current_tier_level + 1,
                        cause="timeout",
                    ),
                )
                await self._escalate_to_next_tier(interaction, channel)
            else:
                await self._escalate(interaction, channel)
            return

        if action == TimeoutAction.RETRY:
            await self._retry(interaction, channel)
            return

        # CANCEL or DEFAULT — resolve future if present, else publish event.
        result = self._build_timeout_result(interaction)
        await self._persist_result(result)

        future = self._pending_futures.pop(interaction.interaction_id, None)
        if future is not None and not future.done():
            future.set_result(result)
        else:
            await self._trigger_rehydration(interaction, result)

    async def _escalate_to_next_tier(
        self,
        interaction: HumanInteraction,
        channel: str,
        cause: str = "timeout",
        _depth: int = 0,
    ) -> None:
        """Move the interaction to the next applicable tier in its policy.

        Handles:
        - Severity / business-hours skip at tier-entry (also on advance).
        - Action failure: advances to the next tier instead of silently
          resolving with empty metadata.
        - Depth guard: aborts after traversing all tiers to prevent runaway
          recursion.

        Args:
            interaction: The current interaction.
            channel: The originating channel name (used as fallback).
            cause: Why we are advancing — one of ``"timeout"``,
                ``"reject"``, ``"business_hours_off"``, ``"action_failed"``.
            _depth: Internal recursion depth counter (DO NOT pass externally).
        """
        if not interaction.policy or not interaction.policy.tiers:
            self.logger.warning(
                "Cannot escalate interaction %s: no policy tiers defined.",
                interaction.interaction_id,
            )
            await self._finish_with_timeout(interaction)
            return

        max_depth = len(interaction.policy.tiers)
        if _depth >= max_depth:
            self.logger.warning(
                "Escalation depth limit (%d) reached for interaction %s; "
                "terminating chain.",
                max_depth,
                interaction.interaction_id,
            )
            await self._finish_with_timeout(interaction)
            return

        next_level = interaction.current_tier_level + 1
        next_tier = next(
            (t for t in interaction.policy.tiers if t.level == next_level), None
        )

        if not next_tier:
            self.logger.info(
                "Level %d reached for interaction %s. No more tiers.",
                interaction.current_tier_level,
                interaction.interaction_id,
            )
            await self._emit(
                "hitl.chain.exhausted",
                HitlChainExhaustedEvent(
                    interaction_id=interaction.interaction_id,
                    policy_id=interaction.policy_id,
                ),
            )
            await self._finish_with_timeout(interaction)
            return

        # Check business hours at tier-entry time
        now = datetime.now(timezone.utc)
        if next_tier.business_hours is not None and not next_tier.business_hours.contains(now):
            self.logger.info(
                "Tier %d (%s) is off-hours for interaction %s; skipping.",
                next_level,
                next_tier.name,
                interaction.interaction_id,
            )
            # Advance the cursor and recurse to skip this tier
            interaction.current_tier_level = next_level
            await self._update_status(interaction)
            await self._emit(
                "hitl.tier.advanced",
                HitlTierAdvancedEvent(
                    interaction_id=interaction.interaction_id,
                    policy_id=interaction.policy_id,
                    from_level=next_level - 1,
                    to_level=next_level,
                    cause=cause,
                ),
            )
            await self._escalate_to_next_tier(
                interaction, channel,
                cause="business_hours_off",
                _depth=_depth + 1,
            )
            return

        # 1. Update state — persist BEFORE action so a crash mid-action
        #    doesn't lose the cursor position.
        interaction.current_tier_level = next_level
        interaction.status = InteractionStatus.ESCALATED
        await self._update_status(interaction)

        # Guard: do NOT emit hitl.tier.entered when the tier is being skipped
        # due to off-hours (Issue 9). The tier is not actually entered — it is
        # skipped. hitl.tier.entered fires only for tiers we actually execute.
        if cause != "business_hours_off":
            await self._emit(
                "hitl.tier.entered",
                HitlTierEnteredEvent(
                    interaction_id=interaction.interaction_id,
                    policy_id=interaction.policy_id,
                    tier_level=next_level,
                    cause=cause,
                ),
            )
        self.logger.info(
            "Interaction %s entering tier %d (%s), cause=%s",
            interaction.interaction_id,
            next_level,
            next_tier.name,
            cause,
        )

        # For cause="business_hours_off", skip this tier's action entirely
        # (we already advanced the cursor above).
        if cause == "business_hours_off":
            await self._escalate_to_next_tier(
                interaction, channel,
                cause="timeout",
                _depth=_depth + 1,
            )
            return

        # 2. Execute Action if needed
        action_metadata: Dict[str, Any] = {}
        action_failed = False

        if next_tier.action_type in self._actions:
            action = self._actions[next_tier.action_type]
            try:
                action_metadata = await action.execute(interaction, next_tier)
                # Check if the action itself reported an error
                if action_metadata.get("error"):
                    action_failed = True
                    self.logger.warning(
                        "Action %s returned error=True for interaction %s; advancing.",
                        next_tier.action_type,
                        interaction.interaction_id,
                    )
                    await self._emit(
                        "hitl.tier.action_failed",
                        HitlTierActionFailedEvent(
                            interaction_id=interaction.interaction_id,
                            policy_id=interaction.policy_id,
                            tier_level=next_level,
                            kind=action_metadata.get("kind", str(next_tier.action_type.value)),
                            reason=str(action_metadata.get("message", "error=True")),
                        ),
                    )
                else:
                    await self._emit(
                        "hitl.tier.action_executed",
                        HitlTierActionExecutedEvent(
                            interaction_id=interaction.interaction_id,
                            policy_id=interaction.policy_id,
                            tier_level=next_level,
                            kind=action_metadata.get("kind", str(next_tier.action_type.value)),
                            action_metadata=action_metadata,
                        ),
                    )
            except Exception as exc:
                action_failed = True
                self.logger.exception(
                    "Action %s raised for interaction %s; advancing to next tier.",
                    next_tier.action_type,
                    interaction.interaction_id,
                )
                await self._emit(
                    "hitl.tier.action_failed",
                    HitlTierActionFailedEvent(
                        interaction_id=interaction.interaction_id,
                        policy_id=interaction.policy_id,
                        tier_level=next_level,
                        kind=str(next_tier.action_type.value),
                        reason=str(exc),
                    ),
                )

        # 3a. Action failed → advance to next tier instead of resolving with empty metadata
        if action_failed:
            await self._emit(
                "hitl.tier.advanced",
                HitlTierAdvancedEvent(
                    interaction_id=interaction.interaction_id,
                    policy_id=interaction.policy_id,
                    from_level=next_level,
                    to_level=next_level + 1,
                    cause="action_failed",
                ),
            )
            await self._escalate_to_next_tier(
                interaction, channel,
                cause="action_failed",
                _depth=_depth + 1,
            )
            return

        # 3b. Re-dispatch or resolve at this tier
        if next_tier.action_type == EscalationActionType.INTERACT:
            # Apply new timeout BEFORE dispatch so the persisted blob is
            # consistent if we crash between dispatch and task scheduling.
            interaction.target_humans = next_tier.target_humans
            interaction.timeout = next_tier.timeout
            await self._dispatch_to_channel(
                interaction, next_tier.channel_type or channel
            )

            # Start a new timeout for THIS level.
            self._timeout_tasks[interaction.interaction_id] = asyncio.create_task(
                self._handle_timeout(interaction, channel)
            )
        else:
            # For non-INTERACT actions (like TICKET, NOTIFY), resume agent immediately
            # as per fire-and-forget policy.
            self.logger.info(
                "Escalated to Tier %d (%s) for interaction %s. "
                "Resuming agent with action metadata.",
                next_level,
                next_tier.name,
                interaction.interaction_id,
            )
            result = InteractionResult(
                interaction_id=interaction.interaction_id,
                status=InteractionStatus.COMPLETED,
                tier_level=next_level,
                escalated=True,
                action_metadata=action_metadata,
            )
            await self._persist_result(result)

            future = self._pending_futures.pop(interaction.interaction_id, None)
            if future is not None and not future.done():
                future.set_result(result)
            else:
                # Suspend/resume mode — publish event for Orchestrator
                await self._trigger_rehydration(interaction, result)

    async def _finish_with_timeout(self, interaction: HumanInteraction) -> None:
        """Resolve the interaction as timed out."""
        result = self._build_timeout_result(interaction)
        await self._persist_result(result)
        future = self._pending_futures.pop(interaction.interaction_id, None)
        if future is not None and not future.done():
            future.set_result(result)
        else:
            await self._trigger_rehydration(interaction, result)

    async def _escalate(
        self, interaction: HumanInteraction, channel: str
    ) -> None:
        """Escalate to alternate humans when the primary target times out."""
        if not interaction.escalation_targets:
            # No escalation targets — treat as timeout/cancel
            result = self._build_timeout_result(interaction)
            await self._persist_result(result)
            future = self._pending_futures.pop(
                interaction.interaction_id, None
            )
            if future is not None and not future.done():
                future.set_result(result)
            else:
                await self._trigger_rehydration(interaction, result)
            return

        original_future = self._pending_futures.pop(
            interaction.interaction_id, None
        )

        escalated = HumanInteraction(
            interaction_id=str(uuid4()),
            question=interaction.question,
            context=(
                f"{interaction.context or ''}\n\n"
                f"⚠️ Escalated: original recipients "
                f"({', '.join(interaction.target_humans)}) "
                f"did not respond within the time limit."
            ).strip(),
            interaction_type=interaction.interaction_type,
            options=interaction.options,
            form_schema=interaction.form_schema,
            default_response=interaction.default_response,
            target_humans=interaction.escalation_targets,
            consensus_mode=interaction.consensus_mode,
            timeout=interaction.timeout,
            timeout_action=TimeoutAction.CANCEL,  # prevent infinite escalation
            source_agent=interaction.source_agent,
            source_flow=interaction.source_flow,
            source_node=interaction.source_node,
        )

        interaction.status = InteractionStatus.ESCALATED
        await self._update_status(interaction)

        # Recursive call — the escalated interaction gets its own timeout
        escalated_result = await self.request_human_input(
            escalated, channel=channel,
        )

        # Forward escalated result to the original caller
        escalated_result.escalated = True
        if original_future is not None and not original_future.done():
            original_future.set_result(escalated_result)
        else:
            # Original was in suspend mode
            await self._persist_result(InteractionResult(
                interaction_id=interaction.interaction_id,
                status=escalated_result.status,
                responses=escalated_result.responses,
                consolidated_value=escalated_result.consolidated_value,
                timed_out=escalated_result.timed_out,
                escalated=True,
            ))
            await self._trigger_rehydration(interaction, escalated_result)

    async def _retry(
        self, interaction: HumanInteraction, channel: str
    ) -> None:
        """Re-send the interaction to the same targets with a fresh timeout.

        Replaces the current timeout task so that the retry has its own
        deadline. Only retries once — subsequent timeout falls back to CANCEL.
        """
        # Re-dispatch
        await self._dispatch_to_channel(interaction, channel)

        # Replace the timeout task with a new one
        old_task = self._timeout_tasks.pop(interaction.interaction_id, None)
        if old_task and not old_task.done():
            old_task.cancel()

        # Create a modified interaction that won't retry again
        retry_interaction = interaction.model_copy(
            update={"timeout_action": TimeoutAction.CANCEL}
        )
        new_task = asyncio.create_task(
            self._handle_timeout(retry_interaction, channel)
        )
        self._timeout_tasks[interaction.interaction_id] = new_task

    # ------------------------------------------------------------------
    # Rehydration (suspend/resume)
    # ------------------------------------------------------------------

    async def _trigger_rehydration(
        self,
        interaction: HumanInteraction,
        result: InteractionResult,
    ) -> None:
        """Publish a completion event for the suspend/resume pattern."""
        try:
            redis = await self._get_redis()
            await redis.publish(
                "hitl:completed",
                json.dumps({
                    "interaction_id": interaction.interaction_id,
                    "source_agent": interaction.source_agent,
                    "source_flow": interaction.source_flow,
                    "source_node": interaction.source_node,
                }),
            )
        except Exception:
            self.logger.exception(
                "Failed to publish rehydration event for %s",
                interaction.interaction_id,
            )

    # ------------------------------------------------------------------
    # Public introspection helpers
    # ------------------------------------------------------------------

    def has_pending(self, interaction_id: str) -> bool:
        """Return True if there is an active pending future for this interaction.

        Provides a public interface to check pending state without callers
        reaching into ``_pending_futures`` directly (Issue 10).

        Args:
            interaction_id: UUID of the interaction to check.

        Returns:
            ``True`` when a non-done future exists for ``interaction_id``,
            ``False`` otherwise.
        """
        fut = self._pending_futures.get(interaction_id)
        return fut is not None and not fut.done()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release resources."""
        # Cancel timeout tasks
        for task in self._timeout_tasks.values():
            if not task.done():
                task.cancel()
        self._timeout_tasks.clear()

        # Cancel pending futures
        for future in self._pending_futures.values():
            if not future.done():
                future.cancel()
        self._pending_futures.clear()

        # Close registered channels (releases per-channel resources like transcribers)
        for name, channel in self.channels.items():
            if hasattr(channel, "close"):
                try:
                    await channel.close()
                except Exception as exc:
                    self.logger.debug(
                        "Error closing channel %s: %s", name, exc
                    )
        self.channels.clear()

        # Close Redis
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
