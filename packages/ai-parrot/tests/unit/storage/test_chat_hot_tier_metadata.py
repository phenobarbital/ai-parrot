"""FEAT-710 TASK-4551 — hot tier keeps caller metadata."""

import pytest

from parrot.storage.chat import ChatStorage
from parrot.storage.models import ChatMessage, MessageRole


@pytest.mark.asyncio
async def test_hot_tier_turn_contains_usage_and_tenant() -> None:
    """AC-1: Redis ConversationTurn.metadata contains caller keys and fixed keys."""
    # Create a ChatStorage with a stubbed Redis conversation memory
    from unittest.mock import AsyncMock

    mock_redis = AsyncMock()
    mock_redis.get_history = AsyncMock(return_value=None)
    mock_redis.create_history = AsyncMock()
    mock_redis.add_turn = AsyncMock()

    storage = ChatStorage(
        redis=mock_redis,
        dynamo=None,
    )

    # Call save_turn with caller metadata
    turn_id = await storage.save_turn(
        user_id="user1",
        session_id="session1",
        agent_id="agent1",
        user_message="Hello",
        assistant_response="Hi there",
        metadata={"usage": {"total_tokens": 3}, "tenant": "t1"},
    )

    # Verify the turn was added to Redis
    assert mock_redis.add_turn.called
    call_args = mock_redis.add_turn.call_args
    assert len(call_args.args) == 3
    turn = call_args.args[2]  # The third argument is the ConversationTurn

    # AC-1: metadata should contain both caller keys and fixed keys
    assert turn.metadata is not None
    assert isinstance(turn.metadata, dict)

    # Check caller keys are present
    assert "usage" in turn.metadata
    assert turn.metadata["usage"] == {"total_tokens": 3}
    assert "tenant" in turn.metadata
    assert turn.metadata["tenant"] == "t1"

    # Check fixed keys are present
    assert "output_mode" in turn.metadata
    assert "model" in turn.metadata
    assert "provider" in turn.metadata
    assert "response_time_ms" in turn.metadata

    # Verify fixed keys win on conflict (caller metadata should not override fixed keys)
    # The fixed keys should have their original values
    assert turn.metadata["output_mode"] is None  # Not provided in metadata
    assert turn.metadata["model"] is None  # Not provided in metadata
    assert turn.metadata["provider"] is None  # Not provided in metadata
    assert turn.metadata["response_time_ms"] is None  # Not provided in metadata
