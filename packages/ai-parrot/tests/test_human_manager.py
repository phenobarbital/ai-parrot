"""Tests for HumanInteractionManager and HumanDecisionNode."""
import asyncio

import pytest
import pytz
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.human.manager import HumanInteractionManager
from parrot.human.node import HumanDecisionNode
from parrot.human.models import (
    BusinessHours,
    ConsensusMode,
    EscalationActionType,
    EscalationPolicy,
    EscalationTier,
    HumanInteraction,
    HumanResponse,
    InteractionResult,
    InteractionStatus,
    InteractionType,
    Severity,
    TimeoutAction,
)


@pytest.fixture
def mock_channel():
    """Create a mock HumanChannel."""
    channel = MagicMock()
    channel.channel_type = "test"
    channel.send_interaction = AsyncMock(return_value=True)
    channel.send_notification = AsyncMock()
    channel.cancel_interaction = AsyncMock()
    channel.register_response_handler = AsyncMock()
    return channel


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.setex = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.publish = AsyncMock()
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def manager(mock_channel, mock_redis):
    """Create a manager with mocked dependencies."""
    mgr = HumanInteractionManager(channels={"test": mock_channel})
    mgr._redis = mock_redis
    return mgr


class TestConsensusEvaluation:
    """Test consensus logic without Redis/async."""

    def _make_response(self, value, respondent="u1"):
        return HumanResponse(
            interaction_id="test",
            respondent=respondent,
            response_type=InteractionType.APPROVAL,
            value=value,
        )

    def test_first_response_resolves_immediately(self):
        interaction = HumanInteraction(
            question="q",
            target_humans=["u1", "u2"],
            consensus_mode=ConsensusMode.FIRST_RESPONSE,
        )
        responses = [self._make_response(True, "u1")]
        reached, value = HumanInteractionManager._evaluate_consensus(
            interaction, responses
        )
        assert reached is True
        assert value is True

    def test_all_required_unanimous(self):
        interaction = HumanInteraction(
            question="q",
            target_humans=["u1", "u2"],
            consensus_mode=ConsensusMode.ALL_REQUIRED,
        )
        responses = [
            self._make_response(True, "u1"),
            self._make_response(True, "u2"),
        ]
        reached, value = HumanInteractionManager._evaluate_consensus(
            interaction, responses
        )
        assert reached is True
        assert value is True

    def test_all_required_conflict(self):
        interaction = HumanInteraction(
            question="q",
            target_humans=["u1", "u2"],
            consensus_mode=ConsensusMode.ALL_REQUIRED,
        )
        responses = [
            self._make_response(True, "u1"),
            self._make_response(False, "u2"),
        ]
        reached, value = HumanInteractionManager._evaluate_consensus(
            interaction, responses
        )
        assert reached is True
        assert value["conflict"] is True

    def test_all_required_partial(self):
        interaction = HumanInteraction(
            question="q",
            target_humans=["u1", "u2"],
            consensus_mode=ConsensusMode.ALL_REQUIRED,
        )
        responses = [self._make_response(True, "u1")]
        reached, _ = HumanInteractionManager._evaluate_consensus(
            interaction, responses
        )
        assert reached is False

    def test_majority_reached(self):
        interaction = HumanInteraction(
            question="q",
            target_humans=["u1", "u2", "u3"],
            consensus_mode=ConsensusMode.MAJORITY,
        )
        responses = [
            self._make_response(True, "u1"),
            self._make_response(True, "u2"),
        ]
        reached, value = HumanInteractionManager._evaluate_consensus(
            interaction, responses
        )
        assert reached is True
        assert value is True

    def test_majority_not_reached(self):
        interaction = HumanInteraction(
            question="q",
            target_humans=["u1", "u2", "u3"],
            consensus_mode=ConsensusMode.MAJORITY,
        )
        responses = [self._make_response(True, "u1")]
        reached, _ = HumanInteractionManager._evaluate_consensus(
            interaction, responses
        )
        assert reached is False

    def test_quorum_reached(self):
        interaction = HumanInteraction(
            question="q",
            target_humans=["u1", "u2", "u3", "u4"],
            consensus_mode=ConsensusMode.QUORUM,
        )
        # 2 of 4 responded, both agree
        responses = [
            self._make_response(True, "u1"),
            self._make_response(True, "u2"),
        ]
        reached, value = HumanInteractionManager._evaluate_consensus(
            interaction, responses
        )
        assert reached is True
        assert value is True


class TestResponseValidation:
    """Test response validation."""

    def test_matching_type_is_valid(self):
        interaction = HumanInteraction(
            question="q", interaction_type=InteractionType.APPROVAL
        )
        response = HumanResponse(
            interaction_id="x",
            respondent="u1",
            response_type=InteractionType.APPROVAL,
            value=True,
        )
        assert (
            HumanInteractionManager._validate_response(interaction, response)
            is True
        )

    def test_mismatched_type_is_invalid(self):
        interaction = HumanInteraction(
            question="q", interaction_type=InteractionType.APPROVAL
        )
        response = HumanResponse(
            interaction_id="x",
            respondent="u1",
            response_type=InteractionType.FREE_TEXT,
            value="hello",
        )
        assert (
            HumanInteractionManager._validate_response(interaction, response)
            is False
        )


class TestRequestHumanInput:
    """Test the long-polling request flow."""

    @pytest.mark.asyncio
    async def test_sends_to_channel_and_waits(self, manager, mock_channel):
        interaction = HumanInteraction(
            question="Approve?",
            interaction_type=InteractionType.APPROVAL,
            target_humans=["u1"],
            timeout=0.5,
            timeout_action=TimeoutAction.CANCEL,
        )

        # Simulate a response arriving shortly after dispatch
        async def simulate_response():
            await asyncio.sleep(0.1)
            response = HumanResponse(
                interaction_id=interaction.interaction_id,
                respondent="u1",
                response_type=InteractionType.APPROVAL,
                value=True,
            )
            await manager.receive_response(response)

        asyncio.create_task(simulate_response())

        # Load the interaction back when receive_response calls _load_interaction
        manager._redis.get = AsyncMock(
            return_value=interaction.model_dump_json()
        )

        result = await manager.request_human_input(
            interaction, channel="test"
        )

        assert result.status == InteractionStatus.COMPLETED
        assert result.consolidated_value is True
        mock_channel.send_interaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_returns_cancel(self, manager, mock_channel):
        interaction = HumanInteraction(
            question="Will you respond?",
            interaction_type=InteractionType.FREE_TEXT,
            target_humans=["u1"],
            timeout=0.2,
            timeout_action=TimeoutAction.CANCEL,
        )

        result = await manager.request_human_input(
            interaction, channel="test"
        )

        assert result.status == InteractionStatus.TIMEOUT
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_timeout_with_default(self, manager, mock_channel):
        interaction = HumanInteraction(
            question="Approve?",
            interaction_type=InteractionType.APPROVAL,
            target_humans=["u1"],
            timeout=0.2,
            timeout_action=TimeoutAction.DEFAULT,
            default_response=False,
        )

        result = await manager.request_human_input(
            interaction, channel="test"
        )

        assert result.status == InteractionStatus.COMPLETED
        assert result.consolidated_value is False
        assert result.timed_out is True


class TestAsyncMode:
    """Test suspend/resume mode."""

    @pytest.mark.asyncio
    async def test_returns_interaction_id(self, manager):
        interaction = HumanInteraction(
            question="q",
            target_humans=["u1"],
        )
        iid = await manager.request_human_input_async(
            interaction, channel="test"
        )
        assert iid == interaction.interaction_id
        manager._redis.setex.assert_called()


class TestClose:
    """Test cleanup."""

    @pytest.mark.asyncio
    async def test_close_releases_resources(self, manager, mock_redis):
        await manager.close()
        mock_redis.close.assert_called_once()
        assert manager._redis is None
        assert len(manager._pending_futures) == 0


# ---------------------------------------------------------------------------
# HumanDecisionNode tests
# ---------------------------------------------------------------------------

class TestHumanDecisionNode:
    """Tests for HumanDecisionNode.ask() — all manager I/O is mocked."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _result(
        value: object = None,
        status: InteractionStatus = InteractionStatus.COMPLETED,
        **kwargs: object,
    ) -> InteractionResult:
        return InteractionResult(
            interaction_id="test-id",
            status=status,
            consolidated_value=value,
            **kwargs,
        )

    @staticmethod
    def _mock_manager(return_value: InteractionResult) -> AsyncMock:
        mgr = AsyncMock()
        mgr.request_human_input = AsyncMock(return_value=return_value)
        return mgr

    # ------------------------------------------------------------------
    # Guard: no manager
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_no_manager_raises_runtime_error(self):
        node = HumanDecisionNode(name="gate", manager=None)
        with pytest.raises(RuntimeError, match="no manager"):
            await node.ask("Q?")

    # ------------------------------------------------------------------
    # Happy path: completed result
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_returns_consolidated_value_on_completion(self):
        node = HumanDecisionNode(
            name="gate",
            manager=self._mock_manager(self._result(True)),
        )
        assert await node.ask("Approve?") is True

    @pytest.mark.asyncio
    async def test_returns_string_value(self):
        node = HumanDecisionNode(
            name="gate",
            manager=self._mock_manager(self._result("approved")),
        )
        assert await node.ask() == "approved"

    # ------------------------------------------------------------------
    # interaction_config path
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_config_generates_fresh_interaction_id(self):
        mgr = self._mock_manager(self._result("ok"))
        config = HumanInteraction(question="Approve?", target_humans=["u1"])
        original_id = config.interaction_id

        node = HumanDecisionNode(name="gate", manager=mgr, interaction_config=config)
        await node.ask()

        sent: HumanInteraction = mgr.request_human_input.call_args[0][0]
        assert sent.interaction_id != original_id
        assert sent.source_node == "gate"

    @pytest.mark.asyncio
    async def test_config_source_node_is_overridden(self):
        mgr = self._mock_manager(self._result("ok"))
        config = HumanInteraction(
            question="Q?",
            target_humans=["u1"],
            source_node="old_node",
        )
        node = HumanDecisionNode(name="my_gate", manager=mgr, interaction_config=config)
        await node.ask()

        sent: HumanInteraction = mgr.request_human_input.call_args[0][0]
        assert sent.source_node == "my_gate"

    @pytest.mark.asyncio
    async def test_config_question_appended_to_context(self):
        mgr = self._mock_manager(self._result(True))
        config = HumanInteraction(
            question="Approve?",
            context="Base context.",
            target_humans=["u1"],
        )
        node = HumanDecisionNode(name="gate", manager=mgr, interaction_config=config)
        await node.ask("Flow context here")

        sent: HumanInteraction = mgr.request_human_input.call_args[0][0]
        assert "Base context." in sent.context
        assert "Flow context here" in sent.context

    @pytest.mark.asyncio
    async def test_config_original_is_not_mutated(self):
        """model_copy() must not modify the stored interaction_config."""
        mgr = self._mock_manager(self._result(True))
        config = HumanInteraction(
            question="Approve?",
            context="Original context.",
            target_humans=["u1"],
        )
        node = HumanDecisionNode(name="gate", manager=mgr, interaction_config=config)
        await node.ask("Extra context")

        assert config.context == "Original context."

    @pytest.mark.asyncio
    async def test_config_no_question_context_unchanged(self):
        """Empty runtime question must not alter the interaction context."""
        mgr = self._mock_manager(self._result(True))
        config = HumanInteraction(
            question="Approve?",
            context="Existing context.",
            target_humans=["u1"],
        )
        node = HumanDecisionNode(name="gate", manager=mgr, interaction_config=config)
        await node.ask()  # empty question

        sent: HumanInteraction = mgr.request_human_input.call_args[0][0]
        assert sent.context == "Existing context."

    # ------------------------------------------------------------------
    # source_agent / source_flow resolution (is not None logic)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_source_agent_none_falls_back_to_config(self):
        mgr = self._mock_manager(self._result("ok"))
        config = HumanInteraction(
            question="Q?",
            source_agent="config_agent",
            target_humans=["u1"],
        )
        node = HumanDecisionNode(
            name="gate",
            manager=mgr,
            interaction_config=config,
            source_agent=None,   # explicit None → fall back to config
        )
        await node.ask()
        sent: HumanInteraction = mgr.request_human_input.call_args[0][0]
        assert sent.source_agent == "config_agent"

    @pytest.mark.asyncio
    async def test_source_agent_overrides_config(self):
        mgr = self._mock_manager(self._result("ok"))
        config = HumanInteraction(
            question="Q?",
            source_agent="config_agent",
            target_humans=["u1"],
        )
        node = HumanDecisionNode(
            name="gate",
            manager=mgr,
            interaction_config=config,
            source_agent="override_agent",
        )
        await node.ask()
        sent: HumanInteraction = mgr.request_human_input.call_args[0][0]
        assert sent.source_agent == "override_agent"

    # ------------------------------------------------------------------
    # No-config path
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_no_config_uses_runtime_question(self):
        mgr = self._mock_manager(self._result("done"))
        node = HumanDecisionNode(name="gate", manager=mgr, target_humans=["u1"])
        await node.ask("What to do?")

        sent: HumanInteraction = mgr.request_human_input.call_args[0][0]
        assert sent.question == "What to do?"

    @pytest.mark.asyncio
    async def test_no_config_defaults_to_free_text(self):
        mgr = self._mock_manager(self._result("ok"))
        node = HumanDecisionNode(name="gate", manager=mgr, target_humans=["u1"])
        await node.ask("Q?")

        sent: HumanInteraction = mgr.request_human_input.call_args[0][0]
        assert sent.interaction_type == InteractionType.FREE_TEXT

    @pytest.mark.asyncio
    async def test_no_config_uses_custom_interaction_type(self):
        """Constructor interaction_type param must be forwarded in the no-config path."""
        mgr = self._mock_manager(self._result(True))
        node = HumanDecisionNode(
            name="gate",
            manager=mgr,
            target_humans=["u1"],
            interaction_type=InteractionType.APPROVAL,
        )
        await node.ask("Approve?")

        sent: HumanInteraction = mgr.request_human_input.call_args[0][0]
        assert sent.interaction_type == InteractionType.APPROVAL

    @pytest.mark.asyncio
    async def test_no_config_empty_question_uses_fallback(self):
        mgr = self._mock_manager(self._result("ok"))
        node = HumanDecisionNode(name="my_gate", manager=mgr)
        await node.ask()  # empty question

        sent: HumanInteraction = mgr.request_human_input.call_args[0][0]
        assert "my_gate" in sent.question

    # ------------------------------------------------------------------
    # Terminal statuses: TIMEOUT and CANCELLED return InteractionResult
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_timeout_returns_full_interaction_result(self):
        timeout_result = self._result(status=InteractionStatus.TIMEOUT, timed_out=True)
        mgr = self._mock_manager(timeout_result)
        node = HumanDecisionNode(name="gate", manager=mgr)

        result = await node.ask("Q?")

        assert result is timeout_result
        assert result.status == InteractionStatus.TIMEOUT
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_cancelled_returns_full_interaction_result(self):
        cancelled_result = self._result(status=InteractionStatus.CANCELLED)
        mgr = self._mock_manager(cancelled_result)
        node = HumanDecisionNode(name="gate", manager=mgr)

        result = await node.ask("Q?")

        assert result is cancelled_result
        assert result.status == InteractionStatus.CANCELLED

    # ------------------------------------------------------------------
    # Infrastructure error → re-raise
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_reraises_infrastructure_errors(self):
        mgr = AsyncMock()
        mgr.request_human_input = AsyncMock(
            side_effect=ConnectionError("Redis connection refused")
        )
        node = HumanDecisionNode(name="gate", manager=mgr)

        with pytest.raises(RuntimeError, match="failed to obtain human input"):
            await node.ask("Q?")

    @pytest.mark.asyncio
    async def test_reraised_error_chains_original_cause(self):
        original = ValueError("unexpected payload")
        mgr = AsyncMock()
        mgr.request_human_input = AsyncMock(side_effect=original)
        node = HumanDecisionNode(name="gate", manager=mgr)

        with pytest.raises(RuntimeError) as exc_info:
            await node.ask("Q?")
        assert exc_info.value.__cause__ is original

    # ------------------------------------------------------------------
    # Consensus conflict dict
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_conflict_dict_is_returned_as_value(self):
        conflict = {"conflict": True, "responses": [True, False]}
        mgr = self._mock_manager(self._result(conflict))
        node = HumanDecisionNode(name="gate", manager=mgr)

        result = await node.ask("Q?")

        assert result == conflict
        assert result["conflict"] is True

    # ------------------------------------------------------------------
    # Escalated result: log + return consolidated_value
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_escalated_result_still_returns_value(self):
        escalated = self._result("approved", escalated=True)
        mgr = self._mock_manager(escalated)
        node = HumanDecisionNode(name="gate", manager=mgr)

        assert await node.ask("Q?") == "approved"

    # ------------------------------------------------------------------
    # FSM interface contract
    # ------------------------------------------------------------------

    def test_name_property(self):
        node = HumanDecisionNode(name="approval_gate", manager=AsyncMock())
        assert node.name == "approval_gate"

    def test_is_configured_is_true(self):
        node = HumanDecisionNode(name="gate", manager=AsyncMock())
        assert node.is_configured is True

    def test_tool_manager_is_none(self):
        node = HumanDecisionNode(name="gate", manager=AsyncMock())
        assert node.tool_manager is None


# ==========================================================================
# FEAT-194 TASK-1277 tests — action-failure fix + advance_chain + TTL
# ==========================================================================

def _make_policy(*tiers):
    return EscalationPolicy(name="test-policy", tiers=list(tiers))


def _notify_tier(level, action_metadata=None, target_humans=None, business_hours=None, min_severity=None):
    meta = action_metadata or {"kind": "email", "to": ["ops@x.com"]}
    return EscalationTier(
        level=level,
        name=f"L{level}",
        action_type=EscalationActionType.NOTIFY,
        action_metadata=meta,
        target_humans=target_humans or [],
        business_hours=business_hours,
        min_severity=min_severity,
    )


def _interact_tier(level, target_humans):
    return EscalationTier(
        level=level,
        name=f"L{level}",
        action_type=EscalationActionType.INTERACT,
        target_humans=target_humans,
    )


@pytest.fixture
def mgr_with_redis():
    """Manager with fully mocked Redis and no real channels."""
    redis = AsyncMock()
    redis.setex = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.publish = AsyncMock()
    redis.close = AsyncMock()
    mgr = HumanInteractionManager()
    mgr._redis = redis
    return mgr


class TestActionFailureAdvances:
    """Tests for action-failure detection and tier advancement."""

    async def test_action_error_dict_advances_to_next_tier(self, mgr_with_redis):
        """When action returns error=True, manager advances to next tier."""
        mgr = mgr_with_redis

        # Tier 1: NOTIFY that returns error=True; Tier 2: NOTIFY that succeeds
        policy = _make_policy(
            _notify_tier(1, {"kind": "email", "to": ["a@b.com"]}),
            _notify_tier(2, {"kind": "email", "to": ["b@b.com"]}),
        )
        interaction = HumanInteraction(
            question="Test?",
            policy=policy,
            current_tier_level=0,
            policy_id="p1",
        )
        mgr._policies["p1"] = policy

        # Make tier-1 action fail; tier-2 action succeed
        action_results = [
            {"message": "fail", "error": True},
            {"message": "ok tier2", "status": "sent"},
        ]
        call_count = {"n": 0}

        async def mock_execute(interaction_obj, tier_obj):
            idx = call_count["n"]
            call_count["n"] += 1
            return action_results[idx]

        mgr._actions[EscalationActionType.NOTIFY].execute = mock_execute
        # Capture persist_result calls
        persisted = []
        async def fake_persist_result(result):
            persisted.append(result)
        mgr._persist_result = fake_persist_result
        mgr._persist_interaction = AsyncMock()
        mgr._update_status = AsyncMock()
        mgr._trigger_rehydration = AsyncMock()

        await mgr._escalate_to_next_tier(interaction, "test", cause="timeout")

        # Should have attempted both tiers
        assert call_count["n"] == 2
        assert persisted, "A result should have been persisted"
        final = persisted[-1]
        assert final.tier_level == 2
        assert final.action_metadata.get("message") == "ok tier2"

    async def test_all_tiers_fail_terminates_cleanly(self, mgr_with_redis):
        """When all tiers fail, chain terminates via _finish_with_timeout."""
        mgr = mgr_with_redis

        policy = _make_policy(
            _notify_tier(1),
            _notify_tier(2),
        )
        interaction = HumanInteraction(
            question="Test?",
            policy=policy,
            current_tier_level=0,
            policy_id="p1",
        )
        mgr._policies["p1"] = policy

        async def always_fail(interaction_obj, tier_obj):
            return {"message": "fail", "error": True}

        mgr._actions[EscalationActionType.NOTIFY].execute = always_fail
        persisted = []
        async def fake_persist_result(result):
            persisted.append(result)
        mgr._persist_result = fake_persist_result
        mgr._persist_interaction = AsyncMock()
        mgr._update_status = AsyncMock()
        mgr._trigger_rehydration = AsyncMock()

        await mgr._escalate_to_next_tier(interaction, "test", cause="timeout")

        assert persisted
        # Chain exhausted → terminates with TIMEOUT-like status
        final = persisted[-1]
        assert final.status in (InteractionStatus.TIMEOUT, InteractionStatus.CANCELLED)


class TestAdvanceChainPublic:
    """Tests for the public advance_chain() method."""

    async def test_advance_chain_reject_picks_next_tier(self, mgr_with_redis):
        """advance_chain(cause='reject') advances to the next tier."""
        mgr = mgr_with_redis

        policy = _make_policy(
            _interact_tier(1, ["u1"]),
            _notify_tier(2),
        )
        interaction = HumanInteraction(
            question="?",
            policy=policy,
            current_tier_level=1,  # currently at tier 1
            policy_id="p1",
        )
        mgr._policies["p1"] = policy

        serialised = interaction.model_dump_json()
        mgr._redis.get = AsyncMock(side_effect=[serialised, None])

        advanced_to = []
        async def fake_next_tier(inter, ch, cause="timeout", _depth=0):
            advanced_to.append(cause)
        mgr._escalate_to_next_tier = fake_next_tier

        await mgr.advance_chain(interaction.interaction_id, cause="reject")
        assert advanced_to == ["reject"]

    async def test_advance_chain_unknown_id_is_silent(self, mgr_with_redis):
        """advance_chain with an unknown id is silently ignored."""
        mgr = mgr_with_redis
        mgr._redis.get = AsyncMock(return_value=None)
        # Should not raise
        await mgr.advance_chain("nonexistent-id", cause="timeout")

    async def test_advance_chain_already_resolved_is_silent(self, mgr_with_redis):
        """advance_chain does nothing when result already persisted."""
        mgr = mgr_with_redis

        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="?",
            policy=policy,
            current_tier_level=1,
        )
        result = InteractionResult(
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.COMPLETED,
        )
        # Load interaction, then load result
        mgr._redis.get = AsyncMock(side_effect=[
            interaction.model_dump_json(),  # _load_interaction
            result.model_dump_json(),       # get_result
        ])
        called = []
        async def fake_next_tier(*a, **k):
            called.append(True)
        mgr._escalate_to_next_tier = fake_next_tier

        await mgr.advance_chain(interaction.interaction_id, cause="reject")
        assert not called, "Should not advance an already-resolved interaction"


class TestStartingTierSelection:
    """Tests for severity-driven starting tier selection in request_human_input."""

    async def test_select_starting_tier_called_with_severity(self, mgr_with_redis):
        """_resolve_interaction_policy sets current_tier_level from select_starting_tier."""
        mgr = mgr_with_redis

        policy = _make_policy(
            _notify_tier(1, min_severity=Severity.NORMAL),
            _notify_tier(2, min_severity=Severity.HIGH),
        )
        mgr._policies["p1"] = policy
        interaction = HumanInteraction(
            question="?",
            policy_id="p1",
            severity=Severity.NORMAL,
        )
        await mgr._resolve_interaction_policy(interaction)
        # NORMAL qualifies for L1 (min_severity=NORMAL <= NORMAL)
        assert interaction.current_tier_level == 0  # level-1 means starts at 0

    async def test_no_applicable_tier_leaves_level_zero(self, mgr_with_redis):
        """When no tier is applicable, current_tier_level stays 0."""
        mgr = mgr_with_redis

        policy = _make_policy(
            _notify_tier(1, min_severity=Severity.CRITICAL),
        )
        mgr._policies["p1"] = policy
        interaction = HumanInteraction(
            question="?",
            policy_id="p1",
            severity=Severity.LOW,
        )
        await mgr._resolve_interaction_policy(interaction)
        assert interaction.current_tier_level == 0


class TestRedisTtlMultiTier:
    """Tests for the extended Redis TTL formula."""

    def test_ttl_covers_sum_of_tier_timeouts(self):
        """Multi-tier TTL is at least the sum of tier timeouts."""
        mgr = HumanInteractionManager()
        policy = _make_policy(
            EscalationTier(
                level=1, name="L1",
                timeout=1800,
                action_type=EscalationActionType.NOTIFY,
                action_metadata={"kind": "email", "to": ["a@b"]},
            ),
            EscalationTier(
                level=2, name="L2",
                timeout=3600,
                action_type=EscalationActionType.NOTIFY,
                action_metadata={"kind": "email", "to": ["b@b"]},
            ),
        )
        interaction = HumanInteraction(
            question="?",
            policy=policy,
            timeout=3600.0,
        )
        ttl = mgr._compute_ttl(interaction)
        # sum(1800, 3600) + 60 = 5460 > 3600 + 60
        assert ttl >= 5460

    def test_ttl_capped_at_24h(self):
        """TTL never exceeds 86400 (24h)."""
        mgr = HumanInteractionManager()
        policy = _make_policy(
            EscalationTier(
                level=1, name="L1",
                timeout=50000,
                action_type=EscalationActionType.NOTIFY,
                action_metadata={"kind": "email", "to": ["a@b"]},
            ),
            EscalationTier(
                level=2, name="L2",
                timeout=50000,
                action_type=EscalationActionType.NOTIFY,
                action_metadata={"kind": "email", "to": ["b@b"]},
            ),
        )
        interaction = HumanInteraction(question="?", policy=policy)
        ttl = mgr._compute_ttl(interaction)
        assert ttl == 86400  # capped


class TestRejectDetectorIntegration:
    """Tests for RejectIntentDetector wiring into receive_response (TASK-1278)."""

    async def test_reject_intent_routes_to_advance_chain(self, mgr_with_redis):
        """Free-text response with escalation intent calls advance_chain(cause='reject')."""
        from parrot.human.escalation_intent import RejectIntentDetector

        mgr = mgr_with_redis
        detector = RejectIntentDetector()
        mgr._reject_detector = detector

        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="How can I help?",
            policy=policy,
            interaction_type=InteractionType.FREE_TEXT,
        )
        mgr._redis.get = AsyncMock(return_value=interaction.model_dump_json())

        response = HumanResponse(
            interaction_id=interaction.interaction_id,
            value="I need a human",
            respondent="user1",
            response_type=InteractionType.FREE_TEXT,
        )

        advanced = []
        async def fake_advance(iid, cause):
            advanced.append(cause)
        mgr.advance_chain = fake_advance

        await mgr.receive_response(response)
        assert advanced == ["reject"]

    async def test_reject_intent_does_not_accumulate(self, mgr_with_redis):
        """When escalation intent is detected, response is NOT accumulated."""
        from parrot.human.escalation_intent import RejectIntentDetector

        mgr = mgr_with_redis
        detector = RejectIntentDetector()
        mgr._reject_detector = detector

        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="How can I help?",
            policy=policy,
            interaction_type=InteractionType.FREE_TEXT,
        )
        mgr._redis.get = AsyncMock(return_value=interaction.model_dump_json())

        response = HumanResponse(
            interaction_id=interaction.interaction_id,
            value="pasame con un humano",
            respondent="user1",
            response_type=InteractionType.FREE_TEXT,
        )

        mgr.advance_chain = AsyncMock()
        mgr._persist_responses = AsyncMock()

        await mgr.receive_response(response)

        mgr.advance_chain.assert_called_once_with(interaction.interaction_id, cause="reject")
        mgr._persist_responses.assert_not_called()

    async def test_no_detector_configured_accumulates_normally(self, mgr_with_redis):
        """Without a detector, 'I need a human' is accumulated as a regular response."""
        mgr = mgr_with_redis
        # No detector — default None
        assert mgr._reject_detector is None

        policy = _make_policy(_notify_tier(1))
        interaction = HumanInteraction(
            question="How can I help?",
            policy=policy,
            interaction_type=InteractionType.FREE_TEXT,
        )
        responses_store = []
        mgr._redis.get = AsyncMock(return_value=interaction.model_dump_json())
        mgr._load_responses = AsyncMock(return_value=[])
        mgr._persist_responses = AsyncMock(side_effect=lambda iid, rs: responses_store.extend(rs))
        mgr._evaluate_consensus = MagicMock(return_value=(False, None))
        mgr._update_status = AsyncMock()

        response = HumanResponse(
            interaction_id=interaction.interaction_id,
            value="I need a human",
            respondent="user1",
            response_type=InteractionType.FREE_TEXT,
        )
        await mgr.receive_response(response)
        assert len(responses_store) == 1  # response was accumulated
