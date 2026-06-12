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

        config = TelegramAgentConfig(name="test", chatbot_id="test_agent")

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
        assert "tool" in cmd_names
        assert "skill" in cmd_names
        assert "function" in cmd_names
        assert "question" in cmd_names
        assert "call" in cmd_names

    def test_includes_jira_commands_when_handlers_are_registered(self):
        """Jira handler registration should feed /commands and bot menu."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        agent = MagicMock()
        bot = MagicMock()
        config = TelegramAgentConfig(name="Test", chatbot_id="test")
        app = {"jira_oauth_manager": MagicMock()}

        with patch("parrot.integrations.telegram.wrapper.CallbackRegistry") as mock_cb:
            mock_cb.return_value.discover_from_agent.return_value = 0
            mock_cb.return_value.prefixes = []
            wrapper = TelegramAgentWrapper(
                agent=agent,
                bot=bot,
                config=config,
                app=app,
            )

        cmd_names = [c.command for c in wrapper.get_bot_commands()]

        assert "connect_jira" in cmd_names
        assert "disconnect_jira" in cmd_names
        assert "jira_status" in cmd_names

    def test_omits_jira_commands_when_handlers_are_not_registered(self):
        """Jira commands should not be advertised without an OAuth manager."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        agent = MagicMock()
        bot = MagicMock()
        config = TelegramAgentConfig(name="Test", chatbot_id="test")

        with patch("parrot.integrations.telegram.wrapper.CallbackRegistry") as mock_cb:
            mock_cb.return_value.discover_from_agent.return_value = 0
            mock_cb.return_value.prefixes = []
            wrapper = TelegramAgentWrapper(
                agent=agent,
                bot=bot,
                config=config,
            )

        cmd_names = [c.command for c in wrapper.get_bot_commands()]

        assert "connect_jira" not in cmd_names
        assert "disconnect_jira" not in cmd_names
        assert "jira_status" not in cmd_names

    def test_wrapper_discovers_agent_commands_without_manager_input(self):
        """Direct wrapper callers should still expose @telegram_command methods."""
        from parrot.integrations.telegram.decorators import telegram_command
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        class Agent:
            name = "TestBot"
            description = "A test bot"

            @telegram_command("agent_ping", description="Ping the agent")
            async def ping(self, raw: str = "") -> str:
                return raw or "pong"

        bot = MagicMock()
        config = TelegramAgentConfig(name="Test", chatbot_id="test")

        with patch("parrot.integrations.telegram.wrapper.CallbackRegistry") as mock_cb:
            mock_cb.return_value.discover_from_agent.return_value = 0
            mock_cb.return_value.prefixes = []
            wrapper = TelegramAgentWrapper(
                agent=Agent(),
                bot=bot,
                config=config,
            )

        cmd_names = [c.command for c in wrapper.get_bot_commands()]

        assert "agent_ping" in cmd_names


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
        s1 = TelegramUserSession(
            telegram_id=1, telegram_first_name="John", telegram_last_name="Doe"
        )
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
        mock_response.json = AsyncMock(
            return_value={
                "user_id": "uid-42",
                "display_name": "Test User",
                "token": "session-tok",
            }
        )
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
            name="Test",
            chatbot_id="test",
            auth_url="https://example.com/api/v1/auth/login",
            enable_login=True,
        )
        wrapper._agent_commands = []
        wrapper._auth_client = NavigatorAuthClient(
            "https://example.com/api/v1/auth/login"
        )
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
        assert (
            config.login_page_url
            == "https://example.ngrok.app/static/telegram/login.html"
        )
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

        session = TelegramUserSession(
            telegram_id=1, telegram_first_name="Jesus", telegram_last_name="Lara"
        )
        session.set_authenticated(
            nav_user_id="uid-1",
            session_token="tok",
            display_name="Jesus Lara",
            email="jlara@trocglobal.com",
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


class TestBotCommandSanitization:
    """Regression tests: a bad @telegram_command must not wipe the whole menu.

    The symptom was that newer agents using ``@telegram_command`` saw no
    menu at all — not even ``/start`` or ``/login`` — because Telegram
    rejected the batched ``setMyCommands`` over a single malformed entry
    (newline in a docstring-derived description, uppercase command name,
    oversized description) and the wrapper silently ate the error.
    """

    def test_sanitize_command_name_strips_slash_and_lowercases(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert TelegramAgentWrapper._sanitize_command_name("/Login") == "login"
        assert TelegramAgentWrapper._sanitize_command_name("MyCmd") == "mycmd"

    def test_sanitize_command_name_replaces_hyphens_and_whitespace(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert TelegramAgentWrapper._sanitize_command_name("run-report") == "run_report"
        assert TelegramAgentWrapper._sanitize_command_name("run report") == "run_report"

    def test_sanitize_command_name_drops_invalid_chars(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert TelegramAgentWrapper._sanitize_command_name("cmd!@#") == "cmd"

    def test_sanitize_command_name_truncates_to_32(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        result = TelegramAgentWrapper._sanitize_command_name("a" * 100)
        assert result is not None
        assert len(result) == 32

    def test_sanitize_command_name_returns_none_for_empty(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert TelegramAgentWrapper._sanitize_command_name("") is None
        assert TelegramAgentWrapper._sanitize_command_name("!!!") is None
        assert TelegramAgentWrapper._sanitize_command_name(None) is None

    def test_sanitize_description_collapses_newlines(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        docstring = "\n    First line.\n\n    Second line.\n    "
        result = TelegramAgentWrapper._sanitize_command_description(
            docstring, fallback="fb"
        )
        assert "\n" not in result
        assert result == "First line. Second line."

    def test_sanitize_description_falls_back_when_blank(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        result = TelegramAgentWrapper._sanitize_command_description(
            "   ", fallback="/cmd"
        )
        assert result == "/cmd"

    def test_sanitize_description_truncates_to_256(self):
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        long_desc = "x" * 500
        result = TelegramAgentWrapper._sanitize_command_description(
            long_desc, fallback="fb"
        )
        assert len(result) == 256

    def test_get_bot_commands_survives_bad_agent_commands(self):
        """A malformed agent command must be dropped, not wipe the menu."""
        import logging
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.agent = MagicMock()
        wrapper.bot = MagicMock()
        wrapper.config = TelegramAgentConfig(name="Test", chatbot_id="test")
        wrapper._auth_strategy = None
        wrapper._user_sessions = {}
        wrapper.logger = logging.getLogger("test.wrapper")
        wrapper._agent_commands = [
            # Multi-line docstring-style description — previously poisoned the
            # entire batch because Telegram rejects newlines.
            {
                "command": "standup",
                "description": "\n    Run the daily standup.\n\n    Blocks until done.\n    ",
                "parse_mode": "keyword",
                "method_name": "run_standup",
                "method": lambda: None,
            },
            # Empty command name — must be dropped without raising.
            {
                "command": "",
                "description": "no-op",
                "parse_mode": "raw",
                "method_name": "noop",
                "method": lambda: None,
            },
            # Upper-case command — must be normalized, not dropped.
            {
                "command": "MyCmd",
                "description": "does something",
                "parse_mode": "raw",
                "method_name": "my_cmd",
                "method": lambda: None,
            },
        ]

        commands = wrapper.get_bot_commands()
        names = [c.command for c in commands]

        # Defaults still present — this is the actual regression we're fixing.
        assert "start" in names
        assert "help" in names
        assert "question" in names

        # Good-but-messy entries survive after sanitization.
        assert "standup" in names
        assert "mycmd" in names

        # Unnormalizable entry is dropped.
        assert "" not in names

        # No description contains newlines.
        for c in commands:
            assert "\n" not in c.description
            assert 1 <= len(c.description) <= 256

    def test_get_bot_commands_drops_duplicates(self):
        """Duplicate commands must be deduped (Telegram rejects dup in batch)."""
        import logging
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.agent = MagicMock()
        wrapper.bot = MagicMock()
        # A YAML mapping that collides with a built-in default.
        wrapper.config = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            commands={"start": "my_start_method"},
        )
        wrapper._auth_strategy = None
        wrapper._user_sessions = {}
        wrapper.logger = logging.getLogger("test.wrapper")
        wrapper._agent_commands = []

        commands = wrapper.get_bot_commands()
        names = [c.command for c in commands]

        # /start appears exactly once even with a colliding YAML entry.
        assert names.count("start") == 1


class TestTelegramBotManagerMenuDelegation:
    """Regression guard: TelegramBotManager still registers the menu via the wrapper.

    FEAT-220 TASK-1443 — After delegation, ``_register_bot_menu`` must still be
    called by ``_start_bot`` when ``register_menu=True`` and skipped when
    ``register_menu=False``.  The thin delegator body itself is tested separately
    in the wrapper tests.
    """

    def _make_manager(self):
        """Build a minimal TelegramBotManager with a mock BotManager."""
        from parrot.integrations.telegram.manager import TelegramBotManager

        manager = TelegramBotManager.__new__(TelegramBotManager)
        manager.logger = MagicMock()
        mock_bm = MagicMock()
        mock_bm.get_app.side_effect = RuntimeError("no app")
        manager.bot_manager = mock_bm
        manager.bots = {}
        manager._polling_tasks = []
        return manager

    def _make_config(self, *, register_menu: bool = True):
        """Minimal TelegramAgentConfig."""
        from parrot.integrations.telegram.models import TelegramAgentConfig

        return TelegramAgentConfig(
            name="testbot",
            chatbot_id="test-agent",
            bot_token="1234567890:AABBCCDDEEFFaabbccddeeff-test_token",
            register_menu=register_menu,
        )

    @pytest.mark.asyncio
    async def test_start_bot_delegates_menu_when_enabled(self, monkeypatch):
        """register_menu=True: _register_bot_menu is awaited once during _start_bot.

        The ``TelegramAgentWrapper`` constructor does significant work (auth
        strategy build, callback discovery, handler registration) that requires
        a real agent object.  We stub the whole wrapper class with a minimal
        stand-in to keep this test focused on the manager's control flow.
        """
        manager = self._make_manager()
        config = self._make_config(register_menu=True)

        menu_mock = AsyncMock()
        monkeypatch.setattr(manager, "_register_bot_menu", menu_mock)

        mock_agent = MagicMock()
        mock_agent.system_prompt = None
        monkeypatch.setattr(manager, "_get_agent", AsyncMock(return_value=mock_agent))

        # Stub discover_telegram_commands (inspects real methods on real agents).
        monkeypatch.setattr(
            "parrot.integrations.telegram.manager.discover_telegram_commands",
            lambda agent: [],
        )

        # Stub TelegramAgentWrapper to avoid constructor side-effects.
        mock_wrapper = MagicMock()
        mock_wrapper.router = MagicMock()
        monkeypatch.setattr(
            "parrot.integrations.telegram.manager.TelegramAgentWrapper",
            lambda *a, **kw: mock_wrapper,
        )

        with patch("asyncio.create_task", return_value=MagicMock()):
            await manager._start_bot("testbot", config)

        menu_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_bot_skips_menu_when_disabled(self, monkeypatch):
        """register_menu=False: _register_bot_menu is never called."""
        manager = self._make_manager()
        config = self._make_config(register_menu=False)

        menu_mock = AsyncMock()
        monkeypatch.setattr(manager, "_register_bot_menu", menu_mock)

        mock_agent = MagicMock()
        mock_agent.system_prompt = None
        monkeypatch.setattr(manager, "_get_agent", AsyncMock(return_value=mock_agent))

        monkeypatch.setattr(
            "parrot.integrations.telegram.manager.discover_telegram_commands",
            lambda agent: [],
        )

        mock_wrapper = MagicMock()
        mock_wrapper.router = MagicMock()
        monkeypatch.setattr(
            "parrot.integrations.telegram.manager.TelegramAgentWrapper",
            lambda *a, **kw: mock_wrapper,
        )

        with patch("asyncio.create_task", return_value=MagicMock()):
            await manager._start_bot("testbot", config)

        menu_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_register_bot_menu_delegates_to_wrapper(self, monkeypatch):
        """_register_bot_menu body calls wrapper.register_command_menu()."""
        from parrot.integrations.telegram.manager import TelegramBotManager

        manager = TelegramBotManager.__new__(TelegramBotManager)
        manager.logger = MagicMock()

        wrapper_mock = MagicMock()
        wrapper_mock.register_command_menu = AsyncMock()

        await manager._register_bot_menu("testbot", MagicMock(), wrapper_mock)

        wrapper_mock.register_command_menu.assert_awaited_once()


class TestIntegrationBotManagerMenuRegistration:
    """Unit tests for the FEAT-220 call site in IntegrationBotManager.

    TASK-1444 — ``_start_telegram_bot`` now calls
    ``wrapper.register_command_menu()`` (gated on ``config.register_menu``).

    Each test exercises the *real* ``_start_telegram_bot`` method (not a stub)
    by mocking only the external dependencies that would require a live network,
    Redis, or the full aiogram constructor chain:

    * ``_get_agent`` — returns a minimal MagicMock agent.
    * ``aiogram.Bot`` / ``aiogram.Dispatcher`` — aiogram types lazily imported
      inside the method; patched at the module level.
    * ``TelegramAgentWrapper`` — patched at the lazy-import site inside
      ``parrot.integrations.manager`` so the wrapper's constructor is bypassed
      and ``register_command_menu`` is a controllable AsyncMock.
    * ``TelegramHumanChannel`` — patched at the same lazy-import site.
    * ``_ensure_human_manager`` — returns a minimal AsyncMock human manager.
    * ``asyncio.create_task`` — returns a MagicMock task.

    This approach ensures that if the real guard (``if config.register_menu``)
    or the try/except around ``register_command_menu()`` is removed or broken,
    the tests catch it — unlike stub-based tests where the gate logic is
    reproduced in the stub itself.
    """

    def _make_integration_manager(self):
        """Build a minimal IntegrationBotManager without real Redis/BotManager."""
        from parrot.integrations.manager import IntegrationBotManager

        manager = IntegrationBotManager.__new__(IntegrationBotManager)
        manager.logger = MagicMock()
        mock_bm = MagicMock()
        mock_bm.get_app.side_effect = RuntimeError("no app")
        manager.bot_manager = mock_bm
        manager.telegram_bots = {}
        manager._polling_tasks = []
        manager.human_manager = None
        manager._human_redis = None
        return manager

    def _make_tg_config(self, *, register_menu: bool = True):
        from parrot.integrations.telegram.models import TelegramAgentConfig

        return TelegramAgentConfig(
            name="testbot",
            chatbot_id="test-agent",
            bot_token="1234567890:AABBCCDDEEFFaabbccddeeff-test_token",
            register_menu=register_menu,
        )

    def _patch_external_deps(self, monkeypatch, menu_mock):
        """Patch all external dependencies of _start_telegram_bot.

        ``_start_telegram_bot`` uses local (lazy) imports so its dependencies
        must be patched at the *module* level that Python's import cache will
        resolve to:

        * ``aiogram.Bot`` / ``aiogram.Dispatcher`` — patched on the ``aiogram``
          module so the ``from aiogram import Bot, Dispatcher`` inside the
          method picks up our fakes.
        * ``aiogram.client.default.DefaultBotProperties`` / ``aiogram.enums.ParseMode``
          — same approach.
        * ``TelegramAgentWrapper`` — patched on
          ``parrot.integrations.telegram.wrapper`` so the local import resolves
          to our fake factory.
        * ``TelegramHumanChannel`` — patched on ``parrot.human``.

        Returns:
            The mock wrapper instance with ``register_command_menu`` set to
            ``menu_mock``.
        """
        # Stub aiogram classes (lazily imported inside _start_telegram_bot).
        fake_bot = MagicMock()
        fake_dp = MagicMock()
        fake_dp.include_router = MagicMock()

        import aiogram
        import aiogram.client.default
        import aiogram.enums

        monkeypatch.setattr(aiogram, "Bot", lambda **kw: fake_bot, raising=False)
        monkeypatch.setattr(aiogram, "Dispatcher", lambda: fake_dp, raising=False)
        monkeypatch.setattr(aiogram.client.default, "DefaultBotProperties", MagicMock(), raising=False)
        monkeypatch.setattr(aiogram.enums, "ParseMode", MagicMock(), raising=False)

        # Stub TelegramAgentWrapper so the real constructor (Redis, aiogram,
        # PostAuthRegistry, CallbackRegistry, …) is not executed.
        mock_wrapper = MagicMock()
        mock_wrapper.router = MagicMock()
        mock_wrapper.register_command_menu = menu_mock

        import parrot.integrations.telegram.wrapper as wrapper_module
        monkeypatch.setattr(wrapper_module, "TelegramAgentWrapper", lambda *a, **kw: mock_wrapper)

        # Stub TelegramHumanChannel (lazily imported from parrot.human).
        fake_channel = MagicMock()
        fake_channel.router = MagicMock()
        fake_channel.register_response_handler = AsyncMock()
        fake_channel.register_cancel_handler = AsyncMock()

        import parrot.human as human_module
        monkeypatch.setattr(human_module, "TelegramHumanChannel", lambda **kw: fake_channel, raising=False)

        return mock_wrapper

    @pytest.mark.asyncio
    async def test_integration_path_registers_menu_when_enabled(self, monkeypatch):
        """Real _start_telegram_bot calls register_command_menu when register_menu=True."""
        manager = self._make_integration_manager()
        config = self._make_tg_config(register_menu=True)

        menu_mock = AsyncMock()
        mock_wrapper = self._patch_external_deps(monkeypatch, menu_mock)

        mock_agent = MagicMock()
        mock_agent.system_prompt = None
        monkeypatch.setattr(manager, "_get_agent", AsyncMock(return_value=mock_agent))

        fake_human_mgr = MagicMock()
        fake_human_mgr.receive_response = AsyncMock()
        fake_human_mgr.cancel_pending = AsyncMock()
        monkeypatch.setattr(
            manager, "_ensure_human_manager", AsyncMock(return_value=fake_human_mgr)
        )

        with patch("asyncio.create_task", return_value=MagicMock()):
            await manager._start_telegram_bot("testbot", config)

        menu_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_integration_path_skips_menu_when_disabled(self, monkeypatch):
        """Real _start_telegram_bot skips register_command_menu when register_menu=False."""
        manager = self._make_integration_manager()
        config = self._make_tg_config(register_menu=False)

        menu_mock = AsyncMock()
        mock_wrapper = self._patch_external_deps(monkeypatch, menu_mock)

        mock_agent = MagicMock()
        mock_agent.system_prompt = None
        monkeypatch.setattr(manager, "_get_agent", AsyncMock(return_value=mock_agent))

        fake_human_mgr = MagicMock()
        fake_human_mgr.receive_response = AsyncMock()
        fake_human_mgr.cancel_pending = AsyncMock()
        monkeypatch.setattr(
            manager, "_ensure_human_manager", AsyncMock(return_value=fake_human_mgr)
        )

        with patch("asyncio.create_task", return_value=MagicMock()):
            await manager._start_telegram_bot("testbot", config)

        menu_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_integration_path_menu_failure_does_not_abort_startup(
        self, monkeypatch
    ):
        """A menu registration error must be swallowed — real startup must complete."""
        manager = self._make_integration_manager()
        config = self._make_tg_config(register_menu=True)

        menu_boom = AsyncMock(side_effect=RuntimeError("Telegram down"))
        mock_wrapper = self._patch_external_deps(monkeypatch, menu_boom)

        mock_agent = MagicMock()
        mock_agent.system_prompt = None
        monkeypatch.setattr(manager, "_get_agent", AsyncMock(return_value=mock_agent))

        fake_human_mgr = MagicMock()
        fake_human_mgr.receive_response = AsyncMock()
        fake_human_mgr.cancel_pending = AsyncMock()
        monkeypatch.setattr(
            manager, "_ensure_human_manager", AsyncMock(return_value=fake_human_mgr)
        )

        # Must not raise — the real try/except in _start_telegram_bot swallows it.
        with patch("asyncio.create_task", return_value=MagicMock()):
            await manager._start_telegram_bot("testbot", config)

        # Warning must have been logged via the real code path.
        manager.logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_integration_manager_has_register_menu_call(self):
        """Verify the actual _start_telegram_bot source contains the register_menu gate.

        This is a structural guard: if someone refactors _start_telegram_bot
        and removes the gate, this test catches it without needing to run the
        full aiogram stack.
        """
        import inspect
        from parrot.integrations.manager import IntegrationBotManager

        source = inspect.getsource(IntegrationBotManager._start_telegram_bot)
        assert "register_menu" in source, (
            "_start_telegram_bot must check config.register_menu before calling "
            "register_command_menu() (FEAT-220)"
        )
        assert "register_command_menu" in source, (
            "_start_telegram_bot must call wrapper.register_command_menu() (FEAT-220)"
        )



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
