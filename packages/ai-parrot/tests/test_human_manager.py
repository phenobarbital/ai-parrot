"""Tests for HumanInteractionManager and HumanDecisionNode."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.human.manager import HumanInteractionManager
from parrot.human.node import HumanDecisionNode
from parrot.human.models import (
    ConsensusMode,
    HumanInteraction,
    HumanResponse,
    InteractionResult,
    InteractionStatus,
    InteractionType,
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
