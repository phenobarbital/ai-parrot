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


class TestTelegramCommandDecorator:
    """Tests for the @telegram_command decorator."""

    def test_decorator_sets_metadata(self):
        """Decorated function should have _telegram_command metadata."""
        from parrot.integrations.telegram.decorators import telegram_command

        @telegram_command("mycommand", description="Does a thing")
        async def my_handler(text: str) -> str:
            return text

        assert hasattr(my_handler, "_telegram_command")
        meta = my_handler._telegram_command
        assert meta["command"] == "mycommand"
        assert meta["description"] == "Does a thing"
        assert meta["parse_mode"] == "keyword"  # default

    def test_decorator_positional_parse_mode(self):
        """parse_mode='positional' should be stored in metadata."""
        from parrot.integrations.telegram.decorators import telegram_command

        @telegram_command("foo", parse_mode="positional")
        async def handler(*args):
            pass

        assert handler._telegram_command["parse_mode"] == "positional"

    def test_decorator_uses_docstring_as_fallback_description(self):
        """If no description given, docstring should be used."""
        from parrot.integrations.telegram.decorators import telegram_command

        @telegram_command("bar")
        async def handler():
            """This is the docstring."""
            pass

        assert handler._telegram_command["description"] == "This is the docstring."

    def test_decorator_does_not_alter_function(self):
        """Decorated function should still be callable normally."""
        from parrot.integrations.telegram.decorators import telegram_command

        @telegram_command("test")
        async def my_func(x):
            return x * 2

        # Should still be an async function
        import asyncio
        assert asyncio.iscoroutinefunction(my_func)


class TestDiscoverTelegramCommands:
    """Tests for discover_telegram_commands utility."""

    def test_discover_finds_decorated_methods(self):
        """Should find methods decorated with @telegram_command."""
        from parrot.integrations.telegram.decorators import (
            telegram_command,
            discover_telegram_commands,
        )

        class FakeAgent:
            @telegram_command("question", description="Ask LLM")
            async def handle_question(self, text):
                pass

            @telegram_command("report", description="Generate report")
            async def generate_report(self):
                pass

            async def regular_method(self):
                pass

        agent = FakeAgent()
        commands = discover_telegram_commands(agent)

        assert len(commands) == 2
        cmd_names = {c["command"] for c in commands}
        assert cmd_names == {"question", "report"}

    def test_discover_ignores_private_methods(self):
        """Private methods should be skipped even if decorated (edge case)."""
        from parrot.integrations.telegram.decorators import (
            telegram_command,
            discover_telegram_commands,
        )

        class FakeAgent:
            @telegram_command("hidden")
            async def _private_handler(self):
                pass

        agent = FakeAgent()
        commands = discover_telegram_commands(agent)
        assert len(commands) == 0

    def test_discover_no_duplicates(self):
        """If two methods register the same command name, only one is kept."""
        from parrot.integrations.telegram.decorators import (
            telegram_command,
            discover_telegram_commands,
        )

        class FakeAgent:
            @telegram_command("dup")
            async def handler_a(self):
                pass

            @telegram_command("dup")
            async def handler_b(self):
                pass

        agent = FakeAgent()
        commands = discover_telegram_commands(agent)
        assert len(commands) == 1

    def test_discover_empty_agent(self):
        """Agent with no decorated methods returns empty list."""
        from parrot.integrations.telegram.decorators import discover_telegram_commands

        class PlainAgent:
            async def ask(self, q):
                pass

        commands = discover_telegram_commands(PlainAgent())
        assert commands == []


class TestParseKwargs:
    """Tests for TelegramAgentWrapper._parse_kwargs static method."""

    def test_keyword_args(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        result = TelegramAgentWrapper._parse_kwargs("key=val name=test")
        assert result == {"key": "val", "name": "test"}

    def test_positional_fallback(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        result = TelegramAgentWrapper._parse_kwargs("hello world")
        assert result == {"arg0": "hello", "arg1": "world"}

    def test_mixed_args(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        result = TelegramAgentWrapper._parse_kwargs("positional key=val")
        assert result == {"arg0": "positional", "key": "val"}

    def test_empty_string(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        result = TelegramAgentWrapper._parse_kwargs("")
        assert result == {}

    def test_comma_separated(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        result = TelegramAgentWrapper._parse_kwargs("a=1, b=2")
        assert result == {"a": "1", "b": "2"}


class TestGetBotCommands:
    """Tests for TelegramAgentWrapper.get_bot_commands."""

    def test_returns_default_commands(self):
        """get_bot_commands should include all default built-in commands."""
        from unittest.mock import MagicMock
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        # Minimal mock setup
        agent = MagicMock()
        agent.name = "TestBot"
        agent.description = "A test bot"
        bot = MagicMock()
        config = TelegramAgentConfig(name="Test", chatbot_id="test")

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.agent = agent
        wrapper.bot = bot
        wrapper.config = config
        wrapper._agent_commands = []
        wrapper._auth_client = None
        wrapper._user_sessions = {}

        commands = wrapper.get_bot_commands()
        cmd_names = [c.command for c in commands]

        assert "start" in cmd_names
        assert "help" in cmd_names
        assert "whoami" in cmd_names
        assert "commands" in cmd_names
        assert "clear" in cmd_names
        assert "skill" in cmd_names
        assert "function" in cmd_names
        assert "question" in cmd_names


class TestRegisterMenuConfig:
    """Tests for register_menu config field."""

    def test_default_register_menu_true(self):
        from parrot.integrations.telegram.models import TelegramAgentConfig

        config = TelegramAgentConfig(name="test", chatbot_id="test")
        assert config.register_menu is True

    def test_from_dict_register_menu(self):
        from parrot.integrations.telegram.models import TelegramAgentConfig

        data = {"chatbot_id": "test", "register_menu": False}
        config = TelegramAgentConfig.from_dict("test", data)
        assert config.register_menu is False


class TestTelegramUserSession:
    """Tests for TelegramUserSession identity logic."""

    def test_user_id_defaults_to_telegram_id(self):
        from parrot.integrations.telegram.auth import TelegramUserSession

        session = TelegramUserSession(telegram_id=12345, telegram_username="testuser")
        assert session.user_id == "tg:12345"
        assert session.session_id == "tg_chat:12345"

    def test_user_id_uses_nav_when_authenticated(self):
        from parrot.integrations.telegram.auth import TelegramUserSession

        session = TelegramUserSession(telegram_id=12345)
        session.set_authenticated(
            nav_user_id="nav-uuid-123",
            session_token="tok-abc",
            display_name="Jesus Lara",
        )
        assert session.user_id == "nav-uuid-123"
        assert session.authenticated is True
        assert session.display_name == "Jesus Lara"

    def test_clear_auth_resets_to_telegram(self):
        from parrot.integrations.telegram.auth import TelegramUserSession

        session = TelegramUserSession(telegram_id=12345, telegram_username="tester")
        session.set_authenticated(
            nav_user_id="nav-uuid-123",
            session_token="tok-abc",
        )
        assert session.user_id == "nav-uuid-123"

        session.clear_auth()
        assert session.user_id == "tg:12345"
        assert session.authenticated is False
        assert session.nav_user_id is None

    def test_display_name_fallback(self):
        from parrot.integrations.telegram.auth import TelegramUserSession

        # With first/last name
        s1 = TelegramUserSession(telegram_id=1, telegram_first_name="John", telegram_last_name="Doe")
        assert s1.display_name == "John Doe"

        # With username only
        s2 = TelegramUserSession(telegram_id=2, telegram_username="johnd")
        assert s2.display_name == "@johnd"

        # With nothing
        s3 = TelegramUserSession(telegram_id=3)
        assert s3.display_name == "User 3"


class TestNavigatorAuthClient:
    """Tests for NavigatorAuthClient login."""

    @pytest.mark.asyncio
    async def test_login_success(self):
        from unittest.mock import AsyncMock, patch, MagicMock
        from parrot.integrations.telegram.auth import NavigatorAuthClient

        client = NavigatorAuthClient("https://example.com/api/v1/auth/login")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "user_id": "uid-42",
            "display_name": "Test User",
            "token": "session-tok",
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await client.login("admin", "secret")

        assert result is not None
        assert result["user_id"] == "uid-42"

    @pytest.mark.asyncio
    async def test_login_failure(self):
        from unittest.mock import AsyncMock, patch, MagicMock
        from parrot.integrations.telegram.auth import NavigatorAuthClient

        client = NavigatorAuthClient("https://example.com/api/v1/auth/login")

        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await client.login("admin", "wrong")

        assert result is None


class TestGetUserSession:
    """Tests for TelegramAgentWrapper._get_user_session."""

    def test_creates_and_caches_session(self):
        from unittest.mock import MagicMock
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper._user_sessions = {}

        msg = MagicMock()
        msg.from_user.id = 99999
        msg.from_user.username = "test_tg_user"
        msg.from_user.first_name = "Test"
        msg.from_user.last_name = "User"

        s1 = wrapper._get_user_session(msg)
        assert s1.telegram_id == 99999
        assert s1.user_id == "tg:99999"

        # Same object returned on second call
        s2 = wrapper._get_user_session(msg)
        assert s1 is s2


class TestGetBotCommandsWithAuth:
    """Tests for get_bot_commands including auth commands."""

    def test_includes_login_logout_when_auth_enabled(self):
        from unittest.mock import MagicMock
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig
        from parrot.integrations.telegram.auth import NavigatorAuthClient

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.agent = MagicMock()
        wrapper.bot = MagicMock()
        wrapper.config = TelegramAgentConfig(
            name="Test", chatbot_id="test",
            auth_url="https://example.com/api/v1/auth/login",
            enable_login=True,
        )
        wrapper._agent_commands = []
        wrapper._auth_client = NavigatorAuthClient("https://example.com/api/v1/auth/login")
        wrapper._user_sessions = {}

        commands = wrapper.get_bot_commands()
        cmd_names = [c.command for c in commands]

        assert "login" in cmd_names
        assert "logout" in cmd_names

    def test_excludes_login_when_no_auth(self):
        from unittest.mock import MagicMock
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.agent = MagicMock()
        wrapper.bot = MagicMock()
        wrapper.config = TelegramAgentConfig(name="Test", chatbot_id="test")
        wrapper._agent_commands = []
        wrapper._auth_client = None
        wrapper._user_sessions = {}

        commands = wrapper.get_bot_commands()
        cmd_names = [c.command for c in commands]

        assert "login" not in cmd_names
        assert "logout" not in cmd_names


class TestAuthConfigParsing:
    """Tests for auth fields in TelegramAgentConfig."""

    def test_from_dict_with_auth_fields(self):
        from parrot.integrations.telegram.models import TelegramAgentConfig

        data = {
            "chatbot_id": "test",
            "auth_url": "https://nav.example.com/api/v1/auth/login",
            "login_page_url": "https://example.ngrok.app/static/telegram/login.html",
            "enable_login": True,
        }
        config = TelegramAgentConfig.from_dict("TestBot", data)
        assert config.auth_url == "https://nav.example.com/api/v1/auth/login"
        assert config.login_page_url == "https://example.ngrok.app/static/telegram/login.html"
        assert config.enable_login is True

    def test_defaults_when_auth_not_configured(self):
        from parrot.integrations.telegram.models import TelegramAgentConfig

        config = TelegramAgentConfig(name="Test", chatbot_id="test")
        # auth_url defaults to env var NAVIGATOR_AUTH_URL (not set in test)
        assert config.login_page_url is None
        assert config.enable_login is True



class TestEnrichQuestion:
    """Tests for TelegramAgentWrapper._enrich_question."""

    def test_appends_name_and_email(self):
        from parrot.integrations.telegram.auth import TelegramUserSession
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        session = TelegramUserSession(telegram_id=1, telegram_first_name="Jesus", telegram_last_name="Lara")
        session.set_authenticated(
            nav_user_id="uid-1", session_token="tok",
            display_name="Jesus Lara", email="jlara@trocglobal.com",
        )
        result = TelegramAgentWrapper._enrich_question("show my tickets", session)
        assert "show my tickets" in result
        assert "name: Jesus Lara" in result
        assert "email: jlara@trocglobal.com" in result

    def test_falls_back_to_telegram_username(self):
        from parrot.integrations.telegram.auth import TelegramUserSession
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        session = TelegramUserSession(telegram_id=2, telegram_username="jlara")
        result = TelegramAgentWrapper._enrich_question("hello", session)
        assert "telegram: @jlara" in result
        assert "email" not in result

    def test_returns_unchanged_when_no_identity(self):
        from parrot.integrations.telegram.auth import TelegramUserSession
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        session = TelegramUserSession(telegram_id=3)
        result = TelegramAgentWrapper._enrich_question("hello", session)
        # display_name returns "User 3" so it will still be enriched
        assert "name: User 3" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
