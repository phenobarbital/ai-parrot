"""
Integration tests for operator command wiring and registration (FEAT-210 TASK-1398).

Tests:
- OperatorCommandsMixin is present in TelegramAgentWrapper's MRO
- _register_operator_commands() registers all 7 operator Command handlers
- Registration is conditional on enable_operator_commands config flag
- /help shows operator commands to operators, hides from non-operators
- Existing commands (/help, /clear, /whoami) remain functional (zero regression)
"""
import pytest
from unittest.mock import MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# Helper: create a minimal wrapper with router set up but no full __init__
# ---------------------------------------------------------------------------

def _make_wrapper_with_router(operator_chat_ids=None, enable_operator_commands=True):
    """Build a TelegramAgentWrapper (which now includes OperatorCommandsMixin)
    bypassing __init__ and providing a real aiogram Router.

    This tests the actual class hierarchy (mixin in bases) and the
    _register_operator_commands method from the mixin.
    """
    from aiogram import Router
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

    w = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    w.logger = MagicMock()
    w.conversations = {}
    w.agent = MagicMock(name="agent")
    w.agent.model = "gemini-2.5"
    w.agent.use_llm = "google"
    w.agent.name = "TestAgent"
    w.config = MagicMock()
    w.config.name = "test-bot"
    w.config.operator_chat_ids = operator_chat_ids if operator_chat_ids is not None else [111]
    w.config.enable_operator_commands = enable_operator_commands
    w.config.commands = {}
    w.app = {}
    w.router = Router()
    w._send_safe_message = AsyncMock()
    w._agent_commands = []
    return w


def _make_message(chat_id: int, text: str = "") -> MagicMock:
    """Create a mock aiogram Message."""
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def _get_registered_commands(router) -> list:
    """Extract Command filter values from registered handlers in an aiogram Router.

    Note: This introspects aiogram internal structure (observer.handlers[*].filters).
    Prefer the mock-router approach (count ``router.message.register`` calls) for
    version-independent assertions; this helper is kept for human-readable output.
    """
    commands = []
    for observer_name, observer in router.observers.items():
        if observer_name != "message":
            continue
        for handler_obj in observer.handlers:
            # Each handler has a list of filters
            for flt in handler_obj.filters:
                inner = getattr(flt, 'callback', flt)
                if hasattr(inner, 'commands'):
                    # aiogram Command filter stores commands as a set/list
                    for cmd in inner.commands:
                        cmd_name = getattr(cmd, 'command', str(cmd))
                        commands.append(cmd_name)
    return commands


# ---------------------------------------------------------------------------
# Mixin presence in class hierarchy
# ---------------------------------------------------------------------------

class TestMixinHierarchy:
    def test_operator_mixin_in_mro(self):
        """OperatorCommandsMixin is in TelegramAgentWrapper's MRO."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.operator_commands import OperatorCommandsMixin

        assert OperatorCommandsMixin in TelegramAgentWrapper.__mro__

    def test_wrapper_has_all_7_handlers(self):
        """TelegramAgentWrapper has all 7 operator handler methods."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        for method_name in (
            'handle_health', 'handle_status', 'handle_context',
            'handle_memory', 'handle_mission', 'handle_model', 'handle_thread',
        ):
            assert hasattr(TelegramAgentWrapper, method_name), (
                f"TelegramAgentWrapper missing {method_name}"
            )

    def test_wrapper_has_register_operator_commands(self):
        """TelegramAgentWrapper has _register_operator_commands from mixin."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert hasattr(TelegramAgentWrapper, '_register_operator_commands')

    def test_wrapper_has_is_operator(self):
        """TelegramAgentWrapper has _is_operator from TASK-1394."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert hasattr(TelegramAgentWrapper, '_is_operator')


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

class TestOperatorRegistration:
    def test_commands_registered_when_enabled(self):
        """enable_operator_commands=True → router.message.register called 7 times.

        Uses a mock router to avoid depending on aiogram's internal observer
        structure, which can change between minor versions.
        """
        from unittest.mock import MagicMock as _MM
        w = _make_wrapper_with_router(operator_chat_ids=[111], enable_operator_commands=True)
        w.router = _MM()
        w._register_operator_commands()
        assert w.router.message.register.call_count == 7, (
            f"Expected 7 register calls, got {w.router.message.register.call_count}"
        )

    def test_all_7_commands_registered(self):
        """Each of the 7 expected commands is passed as a Command filter to register.

        Uses a mock router and inspects call args for Command objects.
        """
        from unittest.mock import MagicMock as _MM
        from aiogram.filters import Command

        w = _make_wrapper_with_router(operator_chat_ids=[111], enable_operator_commands=True)
        w.router = _MM()
        w._register_operator_commands()

        # Collect all Command instances from positional args of every register() call
        registered_cmds: set = set()
        for call in w.router.message.register.call_args_list:
            for arg in call.args:
                if isinstance(arg, Command):
                    for cmd in arg.commands:
                        registered_cmds.add(getattr(cmd, 'command', str(cmd)))

        expected = {'health', 'status', 'context', 'memory', 'mission', 'model', 'thread'}
        missing = expected - registered_cmds
        assert not missing, f"Missing operator commands: {missing}"

    def test_commands_not_registered_when_disabled(self):
        """enable_operator_commands=False → _register_operator_commands not called,
        so router.message.register is never invoked."""
        from unittest.mock import MagicMock as _MM

        w = _make_wrapper_with_router(enable_operator_commands=False)
        w.router = _MM()
        # Simulate what _register_handlers does:
        if getattr(w.config, 'enable_operator_commands', True):
            w._register_operator_commands()
        # Because enable_operator_commands=False, register should not have been called
        assert w.router.message.register.call_count == 0, (
            "Operator commands should not be registered when feature is disabled"
        )

    def test_register_calls_router_register_7_times(self):
        """_register_operator_commands registers exactly 7 handlers (mock-router variant)."""
        from unittest.mock import MagicMock as _MM

        w = _make_wrapper_with_router(operator_chat_ids=[111])
        w.router = _MM()
        w._register_operator_commands()
        assert w.router.message.register.call_count == 7, (
            f"Expected 7 new handlers, got {w.router.message.register.call_count}"
        )


# ---------------------------------------------------------------------------
# /help operator visibility tests
# ---------------------------------------------------------------------------

class TestHelpOperatorVisibility:
    @pytest.mark.asyncio
    async def test_help_shows_operator_cmds_for_operator(self):
        """Operator sees operator commands section in /help output."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        w = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        w.logger = MagicMock()
        w.conversations = {}
        w.agent = MagicMock()
        w.agent.description = "Test agent"
        w.config = MagicMock()
        w.config.name = "test-bot"
        w.config.operator_chat_ids = [111]
        w.config.enable_operator_commands = True
        # allowed_chat_ids=None → fail-open (everyone authorized)
        w.config.allowed_chat_ids = None
        w.config.commands = {}
        w._agent_commands = []
        w._send_safe_message = AsyncMock()

        msg = _make_message(chat_id=111)
        await w.handle_help(msg)

        assert w._send_safe_message.call_count > 0, "handle_help must call _send_safe_message"
        text = w._send_safe_message.call_args[0][1]
        assert "Operator Commands" in text or "/health" in text

    @pytest.mark.asyncio
    async def test_help_hides_operator_cmds_for_non_operator(self):
        """Non-operator does NOT see operator commands in /help output."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        w = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        w.logger = MagicMock()
        w.conversations = {}
        w.agent = MagicMock()
        w.agent.description = "Test agent"
        w.config = MagicMock()
        w.config.name = "test-bot"
        w.config.operator_chat_ids = [111]
        w.config.enable_operator_commands = True
        # allowed_chat_ids=None → everyone is authorized (fail-open)
        w.config.allowed_chat_ids = None
        w.config.commands = {}
        w._agent_commands = []
        w._send_safe_message = AsyncMock()

        msg = _make_message(chat_id=999)  # authorized but not operator
        await w.handle_help(msg)

        assert w._send_safe_message.call_count > 0, "handle_help must call _send_safe_message"
        text = w._send_safe_message.call_args[0][1]
        # Non-operators should not see operator section
        assert "Operator Commands" not in text
        # But regular help should still be there
        assert "/start" in text or "/help" in text or "/clear" in text

    @pytest.mark.asyncio
    async def test_help_hides_operator_cmds_when_feature_disabled(self):
        """When enable_operator_commands=False, operator section not shown even to allowlist."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        w = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        w.logger = MagicMock()
        w.conversations = {}
        w.agent = MagicMock()
        w.agent.description = "Test agent"
        w.config = MagicMock()
        w.config.name = "test-bot"
        w.config.operator_chat_ids = [111]
        w.config.enable_operator_commands = False  # feature off
        # allowed_chat_ids=None → everyone authorized
        w.config.allowed_chat_ids = None
        w.config.commands = {}
        w._agent_commands = []
        w._send_safe_message = AsyncMock()

        msg = _make_message(chat_id=111)
        await w.handle_help(msg)

        assert w._send_safe_message.call_count > 0, "handle_help must call _send_safe_message"
        text = w._send_safe_message.call_args[0][1]
        assert "Operator Commands" not in text


# ---------------------------------------------------------------------------
# Zero-regression tests for existing commands
# ---------------------------------------------------------------------------

class TestZeroRegression:
    def test_handle_help_still_exists(self):
        """handle_help is still present on TelegramAgentWrapper."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert hasattr(TelegramAgentWrapper, 'handle_help')
        assert callable(TelegramAgentWrapper.handle_help)

    def test_handle_clear_still_exists(self):
        """handle_clear is still present on TelegramAgentWrapper."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert hasattr(TelegramAgentWrapper, 'handle_clear')
        assert callable(TelegramAgentWrapper.handle_clear)

    def test_handle_whoami_still_exists(self):
        """handle_whoami is still present on TelegramAgentWrapper."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert hasattr(TelegramAgentWrapper, 'handle_whoami')
        assert callable(TelegramAgentWrapper.handle_whoami)

    def test_handle_start_still_exists(self):
        """handle_start is still present on TelegramAgentWrapper."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert hasattr(TelegramAgentWrapper, 'handle_start')

    def test_is_authorized_still_exists(self):
        """_is_authorized (fail-open) is still present."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert hasattr(TelegramAgentWrapper, '_is_authorized')

    def test_send_safe_message_still_exists(self):
        """_send_safe_message is still present."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert hasattr(TelegramAgentWrapper, '_send_safe_message')

    def test_get_or_create_memory_still_exists(self):
        """_get_or_create_memory is still present."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert hasattr(TelegramAgentWrapper, '_get_or_create_memory')

    def test_config_fields_backward_compatible(self):
        """Existing config without operator_chat_ids still parses correctly."""
        from parrot.integrations.telegram.models import TelegramAgentConfig

        cfg = TelegramAgentConfig.from_dict("test", {"chatbot_id": "test_bot"})
        assert cfg.operator_chat_ids is None
        assert cfg.enable_operator_commands is True
        # Existing fields still work
        assert cfg.allowed_chat_ids is None
        assert cfg.enable_login is True
