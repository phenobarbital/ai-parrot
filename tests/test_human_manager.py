"""Tests for HumanInteractionManager."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.human.manager import HumanInteractionManager
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
            self._make_response("yes", "u1"),
            self._make_response("yes", "u2"),
        ]
        reached, value = HumanInteractionManager._evaluate_consensus(
            interaction, responses
        )
        assert reached is True
        assert value == "yes"


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
