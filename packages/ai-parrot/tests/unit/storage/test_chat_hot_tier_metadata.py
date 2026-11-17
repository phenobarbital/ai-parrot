"""FEAT-710 TASK-4551 / FEAT-886 — the hot tier keeps the slim presentation subset (usage, tenant, ...)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from parrot.memory.persistence import TurnPresentation
from parrot.storage.chat import ChatStorage
from parrot.storage.models import ChatStorageTurn


@pytest.mark.asyncio
async def test_hot_tier_turn_contains_usage_and_tenant() -> None:
    """AC-1: the hot-tier ConversationTurn.metadata carries usage/tenant and the four fixed keys."""
    mock_redis = AsyncMock()
    mock_redis.upsert_turn = AsyncMock()

    storage = ChatStorage(redis_conversation=mock_redis, dynamodb=None)

    await storage.store_turn(ChatStorageTurn(
        turn_id="t-1", user_id="user1", session_id="session1", agent_id="agent1",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), sequence=1,
        user_message="Hello", assistant_response="Hi there",
        presentation=TurnPresentation(usage={"total_tokens": 3}, tenant="t1"),
    ))

    mock_redis.upsert_turn.assert_awaited_once()
    call_args = mock_redis.upsert_turn.call_args
    assert call_args.args[:2] == ("user1", "session1")
    assert call_args.kwargs == {"chatbot_id": "agent1"}
    turn = call_args.args[2]

    assert isinstance(turn.metadata, dict)
    assert turn.metadata["usage"] == {"total_tokens": 3}
    assert turn.metadata["tenant"] == "t1"
    for key in ("output_mode", "model", "provider", "response_time_ms"):
        assert key in turn.metadata and turn.metadata[key] is None
    assert "cost_usd" not in turn.metadata  # only present when set
    for heavy in ("output", "data", "code", "sources"):
        assert heavy not in turn.metadata  # the hot tier is a cache; the cold row has everything
