"""Shared fixtures for Telegram crew integration tests."""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from parrot.integrations.telegram.crew.agent_card import AgentCard, AgentSkill
from parrot.integrations.telegram.crew.config import TelegramCrewConfig, CrewAgentEntry
from parrot.integrations.telegram.crew.coordinator import CoordinatorBot
from parrot.integrations.telegram.crew.registry import CrewRegistry
from parrot.integrations.telegram.crew.payload import DataPayload


@pytest.fixture
def crew_config():
    """Standard crew configuration with two agents."""
    return TelegramCrewConfig(
        group_id=-1001234567890,
        coordinator_token="000000000:coordinator_fake_token_abc",
        coordinator_username="test_coordinator_bot",
        hitl_user_ids=[123456789],
        agents={
            "TestAgent": CrewAgentEntry(
                chatbot_id="test_agent",
                bot_token="111111111:agent_fake_token_xyz",
                username="test_agent_bot",
                tags=["test"],
                skills=[{"name": "echo", "description": "Echoes input"}],
            ),
            "ReportAgent": CrewAgentEntry(
                chatbot_id="report_agent",
                bot_token="222222222:report_fake_token_abc",
                username="report_agent_bot",
                tags=["reports"],
                skills=[{"name": "report", "description": "Generates reports"}],
            ),
        },
    )


@pytest.fixture
def sample_agent_card():
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
def second_agent_card():
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
def mock_bot():
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
    # Mock bot.me() for BotMentionedFilter / extract_query_from_mention
    bot_user = MagicMock()
    bot_user.username = "test_agent_bot"
    bot_user.id = 999999
    bot.me = AsyncMock(return_value=bot_user)
    return bot


@pytest.fixture
def mock_agent():
    """Mock AI-Parrot agent with ask() method."""
    agent = AsyncMock()
    agent.ask = AsyncMock(return_value="Test response from agent")
    agent.model = "test:model"
    return agent


@pytest.fixture
def registry():
    """Empty CrewRegistry."""
    return CrewRegistry()


@pytest.fixture
def mock_coordinator(registry, mock_bot):
    """CoordinatorBot with a mocked bot for testing."""
    coord = CoordinatorBot(
        token="000000000:coordinator_fake_token_abc",
        group_id=-1001234567890,
        registry=registry,
        username="test_coordinator_bot",
        bot=mock_bot,
    )
    return coord


@pytest.fixture
def mock_payload(tmp_path):
    """DataPayload with a temporary directory."""
    return DataPayload(
        temp_dir=str(tmp_path),
        max_file_size_mb=50,
    )
