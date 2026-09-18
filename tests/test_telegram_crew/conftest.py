"""Shared fixtures for the Telegram crew tests under ``tests/test_telegram_crew``.

The original shared conftest was moved to
``packages/ai-parrot-integrations/tests/test_telegram_crew/conftest.py`` by the
test re-organisation (f523e021d); the tests in this directory were re-added
afterwards (56ea47a54) without it. These mirror the fixtures that
``test_integration.py`` depends on. Modules that define a fixture of the same
name locally keep using their own definition.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.telegram.crew.agent_card import AgentCard, AgentSkill
from parrot.integrations.telegram.crew.registry import CrewRegistry


@pytest.fixture
def sample_agent_card() -> AgentCard:
    """A pre-built AgentCard for testing."""
    return AgentCard(
        agent_id="test_agent",
        agent_name="TestAgent",
        telegram_username="test_agent_bot",
        telegram_user_id=999999,
        model="test:model",
        skills=[AgentSkill(name="echo", description="Echoes input")],
        tags=["test"],
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


@pytest.fixture
def second_agent_card() -> AgentCard:
    """A second AgentCard for multi-agent tests."""
    return AgentCard(
        agent_id="report_agent",
        agent_name="ReportAgent",
        telegram_username="report_agent_bot",
        telegram_user_id=888888,
        model="test:model",
        skills=[AgentSkill(name="report", description="Generates reports")],
        tags=["reports"],
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_bot() -> AsyncMock:
    """Mock aiogram Bot with common methods."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
    bot.send_chat_action = AsyncMock()
    bot.send_document = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.edit_message_text = AsyncMock()
    bot.pin_chat_message = AsyncMock()
    bot.session = AsyncMock()
    bot.session.close = AsyncMock()
    # bot.me() is used by BotMentionedFilter / extract_query_from_mention.
    bot_user = MagicMock()
    bot_user.username = "test_agent_bot"
    bot_user.id = 999999
    bot.me = AsyncMock(return_value=bot_user)
    return bot


@pytest.fixture
def mock_agent() -> AsyncMock:
    """Mock AI-Parrot agent with an ``ask()`` method."""
    agent = AsyncMock()
    agent.ask = AsyncMock(return_value="Test response from agent")
    agent.model = "test:model"
    return agent


@pytest.fixture
def registry() -> CrewRegistry:
    """Empty CrewRegistry."""
    return CrewRegistry()
