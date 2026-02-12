"""Central engine for human-in-the-loop interactions."""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from typing import Any, Dict, List, Optional
from uuid import uuid4

from navconfig.logging import logging

from .channels.base import HumanChannel
from .models import (
    ConsensusMode,
    HumanInteraction,
    HumanResponse,
    InteractionResult,
    InteractionStatus,
    TimeoutAction,
)


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
    ) -> None:
        self.channels: Dict[str, HumanChannel] = channels or {}
        self._redis_url = redis_url
        self._redis = None
        self._pending_futures: Dict[str, asyncio.Future] = {}
        self._timeout_tasks: Dict[str, asyncio.Task] = {}
        self.logger = logging.getLogger("parrot.human.manager")

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    async def _get_redis(self):
        """Lazy-init Redis connection."""
        if self._redis is None:
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

    async def _persist_interaction(self, interaction: HumanInteraction) -> None:
        """Store an interaction in Redis with TTL matching its timeout."""
        redis = await self._get_redis()
        key = f"hitl:interaction:{interaction.interaction_id}"
        ttl = int(interaction.timeout) + 60  # small buffer
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
        data = json.dumps([r.model_dump() for r in responses])
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
            return []

    async def _persist_result(self, result: InteractionResult) -> None:
        """Store the final result in Redis (24h TTL)."""
        redis = await self._get_redis()
        key = f"hitl:result:{result.interaction_id}"
        await redis.setex(key, 86400, result.model_dump_json())

    # ------------------------------------------------------------------
    # Channel registration
    # ------------------------------------------------------------------

    def register_channel(self, name: str, channel: HumanChannel) -> None:
        """Register a communication channel."""
        self.channels[name] = channel

    async def startup(self) -> None:
        """Register response handlers on all channels."""
        for name, channel in self.channels.items():
            await channel.register_response_handler(self.receive_response)
            self.logger.info(
                "Registered response handler for channel: %s", name
            )

    # ------------------------------------------------------------------
    # Public API: long-polling mode
    # ------------------------------------------------------------------

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
        # 1. Persist
        await self._persist_interaction(interaction)

        # 2. Create awaitable future BEFORE dispatch
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_futures[interaction.interaction_id] = future

        # 3. Schedule timeout handler
        timeout_task = asyncio.create_task(
            self._handle_timeout(interaction, channel)
        )
        self._timeout_tasks[interaction.interaction_id] = timeout_task

        # 4. Dispatch to channel (may resolve the future synchronously
        #    for CLI-style channels)
        await self._dispatch_to_channel(interaction, channel)

        # 5. Wait for resolution
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

        channel_impl = self.channels[channel]
        for human_id in interaction.target_humans:
            delivered = await channel_impl.send_interaction(
                interaction, human_id
            )
            if delivered:
                interaction.status = InteractionStatus.DELIVERED
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
    ) -> str:
        """Non-blocking variant that returns the interaction_id immediately.

        The caller serialises its own state and resumes when the result
        appears in Redis (via ``get_result`` or a pub/sub listener).
        """
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

        # Schedule async timeout (publishes timeout result to Redis)
        asyncio.create_task(
            self._handle_async_timeout(interaction, channel)
        )

        return interaction.interaction_id

    async def _handle_async_timeout(
        self, interaction: HumanInteraction, channel: str
    ) -> None:
        """Timeout handler for the async/suspend mode.

        Unlike _handle_timeout, this doesn't resolve a Future — it
        persists the timeout result to Redis and publishes a rehydration
        event so the suspended agent can be resumed with a timeout status.
        """
        await asyncio.sleep(interaction.timeout)

        # Check if already resolved
        existing = await self.get_result(interaction.interaction_id)
        if existing is not None:
            return

        result = self._build_timeout_result(interaction)
        await self._persist_result(result)
        await self._trigger_rehydration(interaction, result)

    async def get_result(
        self, interaction_id: str
    ) -> Optional[InteractionResult]:
        """Poll Redis for a completed interaction result."""
        redis = await self._get_redis()
        raw = await redis.get(f"hitl:result:{interaction_id}")
        if raw is None:
            return None
        return InteractionResult.model_validate_json(raw)

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

        # Resolve in-memory future (long-polling / hot-wait mode)
        future = self._pending_futures.pop(interaction.interaction_id, None)
        if future is not None and not future.done():
            future.set_result(result)
            # Cancel associated timeout task
            timeout_task = self._timeout_tasks.pop(
                interaction.interaction_id, None
            )
            if timeout_task and not timeout_task.done():
                timeout_task.cancel()
        else:
            # Suspend/resume mode — publish event
            await self._trigger_rehydration(interaction, result)

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
            # Build vote counts using a stable hashable key,
            # but return the original typed value (not the stringified key)
            key_to_value = {}
            vote_keys = []
            for r in responses:
                k = _stable_key(r.value)
                key_to_value[k] = r.value
                vote_keys.append(k)
            votes = Counter(vote_keys)
            winner_key, count = votes.most_common(1)[0]
            if count >= threshold:
                return True, key_to_value[winner_key]
            return False, None

        if mode == ConsensusMode.QUORUM:
            # At least half responded, and majority among those
            if total_received < max(total_expected // 2, 1):
                return False, None
            key_to_value = {}
            vote_keys = []
            for r in responses:
                k = _stable_key(r.value)
                key_to_value[k] = r.value
                vote_keys.append(k)
            votes = Counter(vote_keys)
            winner_key, count = votes.most_common(1)[0]
            if count > total_received // 2:
                return True, key_to_value[winner_key]
            return False, None

        return False, None

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

        Used by the long-polling (request_human_input) path.
        """
        await asyncio.sleep(interaction.timeout)

        # If already resolved, nothing to do
        if interaction.interaction_id not in self._pending_futures:
            return

        action = interaction.timeout_action

        if action == TimeoutAction.ESCALATE:
            await self._escalate(interaction, channel)
            return

        if action == TimeoutAction.RETRY:
            await self._retry(interaction, channel)
            return

        # CANCEL or DEFAULT
        result = self._build_timeout_result(interaction)
        await self._persist_result(result)

        future = self._pending_futures.pop(interaction.interaction_id, None)
        if future is not None and not future.done():
            future.set_result(result)

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

        # Close Redis
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
