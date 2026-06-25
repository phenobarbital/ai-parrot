"""
Shared pytest fixtures for the MS Agent SDK integration tests.

All fixtures here avoid importing the ``microsoft_agents.*`` SDK so that
the test suite can run without the optional dependency installed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def msagentsdk_config():
    """Minimal anonymous-auth config for local testing."""
    from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

    return MSAgentSDKConfig(
        name="TestCopilotBot",
        chatbot_id="test_agent",
        anonymous_auth=True,
    )


@pytest.fixture
def mock_bot():
    """Mock ai-parrot AbstractBot that returns a fixed response."""
    bot = AsyncMock()
    bot.ask = AsyncMock(return_value=MagicMock(content="Test response"))
    return bot


@pytest.fixture
def mock_activity_message():
    """Minimal MS Agent SDK Activity JSON for a message."""
    return {
        "type": "message",
        "text": "Hello, agent!",
        "from": {"id": "user-123", "name": "Test User"},
        "conversation": {"id": "conv-456"},
        "channelId": "webchat",
        "serviceUrl": "https://test.botframework.com/",
        "id": "activity-789",
    }


@pytest.fixture
def mock_turn_context():
    """Mock TurnContext with a pre-built message activity."""
    ctx = AsyncMock()
    ctx.activity = MagicMock()
    ctx.activity.type = "message"
    ctx.activity.text = "Hello, agent!"
    ctx.activity.from_property = MagicMock(id="user-123", name="Test User")
    ctx.activity.conversation = MagicMock(id="conv-456")
    ctx.activity.recipient = MagicMock(id="bot-789")
    ctx.activity.members_added = None
    ctx.send_activity = AsyncMock()
    return ctx
