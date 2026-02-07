"""
Tests for Telegram Group Integration.

Tests BotMentionedFilter, extract_query_from_mention, and group message handling.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestBotMentionedFilter:
    """Tests for BotMentionedFilter."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock Bot with username."""
        bot = AsyncMock()
        bot_user = MagicMock()
        bot_user.username = "test_bot"
        bot.me = AsyncMock(return_value=bot_user)
        return bot

    @pytest.fixture
    def filter_instance(self):
        """Create filter instance."""
        from parrot.integrations.telegram.filters import BotMentionedFilter
        return BotMentionedFilter()

    @pytest.mark.asyncio
    async def test_mention_via_entities(self, filter_instance, mock_bot):
        """Message with @test_bot entity should match."""
        message = MagicMock()
        message.text = "Hey @test_bot what is Python?"
        
        entity = MagicMock()
        entity.type = "mention"
        entity.offset = 4
        entity.length = 9  # "@test_bot"
        message.entities = [entity]
        
        result = await filter_instance(message, mock_bot)
        assert result is True

    @pytest.mark.asyncio
    async def test_mention_via_text_fallback(self, filter_instance, mock_bot):
        """Message with @test_bot in text (no entities) should match."""
        message = MagicMock()
        message.text = "Hello @test_bot please help"
        message.entities = None
        
        result = await filter_instance(message, mock_bot)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_mention(self, filter_instance, mock_bot):
        """Message without bot mention should not match."""
        message = MagicMock()
        message.text = "Hello everyone!"
        message.entities = None
        
        result = await filter_instance(message, mock_bot)
        assert result is False

    @pytest.mark.asyncio
    async def test_different_bot_mention(self, filter_instance, mock_bot):
        """Message mentioning different bot should not match."""
        message = MagicMock()
        message.text = "Hey @other_bot what's up?"
        
        entity = MagicMock()
        entity.type = "mention"
        entity.offset = 4
        entity.length = 10  # "@other_bot"
        message.entities = [entity]
        
        result = await filter_instance(message, mock_bot)
        assert result is False

    @pytest.mark.asyncio
    async def test_case_insensitive_mention(self, filter_instance, mock_bot):
        """Mention should be case-insensitive."""
        message = MagicMock()
        message.text = "Hey @TEST_BOT what is AI?"
        message.entities = None
        
        result = await filter_instance(message, mock_bot)
        assert result is True

    @pytest.mark.asyncio
    async def test_empty_text(self, filter_instance, mock_bot):
        """Empty message should not match."""
        message = MagicMock()
        message.text = None
        
        result = await filter_instance(message, mock_bot)
        assert result is False


class TestExtractQueryFromMention:
    """Tests for extract_query_from_mention utility."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock Bot with username."""
        bot = AsyncMock()
        bot_user = MagicMock()
        bot_user.username = "test_bot"
        bot.me = AsyncMock(return_value=bot_user)
        return bot

    @pytest.mark.asyncio
    async def test_simple_mention(self, mock_bot):
        """Extract query from simple @mention."""
        from parrot.integrations.telegram.utils import extract_query_from_mention
        
        message = MagicMock()
        message.text = "@test_bot what is Python?"
        
        result = await extract_query_from_mention(message, mock_bot)
        assert result == "what is Python?"

    @pytest.mark.asyncio
    async def test_mention_in_middle(self, mock_bot):
        """Extract query with @mention in middle of text."""
        from parrot.integrations.telegram.utils import extract_query_from_mention
        
        message = MagicMock()
        message.text = "Hey @test_bot tell me about AI"
        
        result = await extract_query_from_mention(message, mock_bot)
        # Note: removing @mention may leave double spaces, which is acceptable
        assert "Hey" in result and "tell me about AI" in result

    @pytest.mark.asyncio
    async def test_ask_command(self, mock_bot):
        """Extract query from /ask command."""
        from parrot.integrations.telegram.utils import extract_query_from_mention
        
        message = MagicMock()
        message.text = "/ask what is machine learning?"
        
        result = await extract_query_from_mention(message, mock_bot)
        assert result == "what is machine learning?"

    @pytest.mark.asyncio
    async def test_ask_command_with_botname(self, mock_bot):
        """Extract query from /ask@botname command."""
        from parrot.integrations.telegram.utils import extract_query_from_mention
        
        message = MagicMock()
        message.text = "/ask@test_bot what is RAG?"
        
        result = await extract_query_from_mention(message, mock_bot)
        assert result == "what is RAG?"

    @pytest.mark.asyncio
    async def test_empty_query(self, mock_bot):
        """Just @mention with no query should return empty string."""
        from parrot.integrations.telegram.utils import extract_query_from_mention
        
        message = MagicMock()
        message.text = "@test_bot"
        
        result = await extract_query_from_mention(message, mock_bot)
        assert result == ""

    @pytest.mark.asyncio
    async def test_case_insensitive(self, mock_bot):
        """Username removal should be case-insensitive."""
        from parrot.integrations.telegram.utils import extract_query_from_mention
        
        message = MagicMock()
        message.text = "@TEST_BOT explain this"
        
        result = await extract_query_from_mention(message, mock_bot)
        assert result == "explain this"


class TestCommandInGroupFilter:
    """Tests for CommandInGroupFilter."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock Bot with username."""
        bot = AsyncMock()
        bot_user = MagicMock()
        bot_user.username = "test_bot"
        bot.me = AsyncMock(return_value=bot_user)
        return bot

    @pytest.mark.asyncio
    async def test_simple_command(self, mock_bot):
        """Simple /ask command should match."""
        from parrot.integrations.telegram.filters import CommandInGroupFilter
        
        filter_obj = CommandInGroupFilter("ask")
        message = MagicMock()
        message.text = "/ask what is Python?"
        
        result = await filter_obj(message, mock_bot)
        assert result is True

    @pytest.mark.asyncio
    async def test_targeted_command(self, mock_bot):
        """Targeted /ask@test_bot command should match."""
        from parrot.integrations.telegram.filters import CommandInGroupFilter
        
        filter_obj = CommandInGroupFilter("ask")
        message = MagicMock()
        message.text = "/ask@test_bot what is AI?"
        
        result = await filter_obj(message, mock_bot)
        assert result is True

    @pytest.mark.asyncio
    async def test_different_command(self, mock_bot):
        """Different command should not match."""
        from parrot.integrations.telegram.filters import CommandInGroupFilter
        
        filter_obj = CommandInGroupFilter("ask")
        message = MagicMock()
        message.text = "/help"
        
        result = await filter_obj(message, mock_bot)
        assert result is False

    @pytest.mark.asyncio
    async def test_not_a_command(self, mock_bot):
        """Non-command text should not match."""
        from parrot.integrations.telegram.filters import CommandInGroupFilter
        
        filter_obj = CommandInGroupFilter("ask")
        message = MagicMock()
        message.text = "Hello world"
        
        result = await filter_obj(message, mock_bot)
        assert result is False


class TestTelegramAgentConfigGroupSettings:
    """Tests for TelegramAgentConfig group settings."""

    def test_default_group_settings(self):
        """Default config should have group features enabled."""
        from parrot.integrations.telegram.models import TelegramAgentConfig
        
        config = TelegramAgentConfig(
            name="test",
            chatbot_id="test_agent"
        )
        
        assert config.enable_group_mentions is True
        assert config.enable_group_commands is True
        assert config.reply_in_thread is True
        assert config.enable_channel_posts is False

    def test_from_dict_with_group_settings(self):
        """Config should parse group settings from dict."""
        from parrot.integrations.telegram.models import TelegramAgentConfig
        
        data = {
            "chatbot_id": "my_agent",
            "enable_group_mentions": False,
            "enable_group_commands": True,
            "reply_in_thread": False,
            "enable_channel_posts": True,
        }
        
        config = TelegramAgentConfig.from_dict("test", data)
        
        assert config.enable_group_mentions is False
        assert config.enable_group_commands is True
        assert config.reply_in_thread is False
        assert config.enable_channel_posts is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
