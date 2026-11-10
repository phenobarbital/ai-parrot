"""FEAT-848 — AbstractBot warns once at configure() when its client declares no tool loop."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.bots.abstract import AbstractBot


class _ConfigureTestBot(AbstractBot):
    """Concrete shell used to exercise AbstractBot lifecycle behavior."""

    async def ask(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def ask_stream(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def conversation(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def invoke(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None


def _stub_bot() -> AbstractBot:
    """Return an AbstractBot with every configure collaborator stubbed."""
    bot = object.__new__(_ConfigureTestBot)
    bot.logger = MagicMock()
    bot.configure_conversation_memory = MagicMock()
    bot.apply_tooling_specs = AsyncMock(return_value=[])
    bot.configure_kb = AsyncMock()
    bot._use_local_kb = False
    bot._llm_model_explicit = False
    bot._llm_raw = None
    bot._llm_preset = None
    bot._llm_kwargs = {}
    bot._llm_model = None
    bot._resolve_llm_config = MagicMock(return_value=MagicMock(model=None))
    bot._create_llm_client = MagicMock(return_value=MagicMock())
    bot.tool_manager = MagicMock(_server_param_source=None)
    bot.sync_tools = MagicMock()
    bot.get_tools_summary = MagicMock(
        return_value={
            "tools_enabled": False,
            "operation_mode": "",
            "tools_count": 0,
            "categories": [],
            "effective_mode": "",
        }
    )
    bot._define_prompt = MagicMock()
    bot._prompt_builder = None
    bot.define_store_config = MagicMock(return_value=None)
    bot._use_vector = False
    bot._vector_store = None
    bot._refresh_context_recs_from_store = MagicMock()
    bot.warmup_on_configure = False
    bot.store = None
    bot.use_kb = False
    bot._credentials = []
    bot.post_configure = AsyncMock()
    bot._llm_config = None
    bot._events_registry = MagicMock()
    bot.name = "test-bot"
    return bot


def _app() -> SimpleNamespace:
    """Return a truthy app wrapper around a stable resolved app object."""
    real = web.Application()
    real["configured"] = True
    return SimpleNamespace(get_app=lambda: real)


class _NoLoopClient:
    """Client double declaring no text ask() tool loop."""

    supports_tool_loop = False
    client_type = "noloop"


class _LoopClient:
    """Client double declaring a tool loop."""

    supports_tool_loop = True
    client_type = "loop"


def _agent_bot(client: object, *, enable_tools: bool = True, tools: int = 1, mode: str = "adaptive") -> AbstractBot:
    """A bare bot with just the state the helper reads."""
    bot = object.__new__(_ConfigureTestBot)
    bot.logger = MagicMock()
    bot.name = "test-bot"
    bot._llm = client
    bot.enable_tools = enable_tools
    bot.operation_mode = mode
    bot.tool_manager = MagicMock()
    bot.tool_manager.tool_count.return_value = tools
    return bot


def _tool_loop_warnings(bot: AbstractBot) -> list:
    """The warning calls this feature emits (other code may warn too)."""
    return [c for c in bot.logger.warning.call_args_list if "supports_tool_loop=False" in str(c.args[0])]


def test_warns_once_for_agent_mode_no_loop_client() -> None:
    """One warning naming bot, client class, client_type and tool count."""
    bot = _agent_bot(_NoLoopClient())
    bot._warn_if_client_lacks_tool_loop()
    warnings = _tool_loop_warnings(bot)
    assert len(warnings) == 1
    assert warnings[0].args[1:] == ("test-bot", "_NoLoopClient", "noloop", 1)


def test_silent_for_loop_client() -> None:
    """A True client logs nothing."""
    bot = _agent_bot(_LoopClient())
    bot._warn_if_client_lacks_tool_loop()
    assert _tool_loop_warnings(bot) == []


@pytest.mark.parametrize("kwargs", [{"enable_tools": False}, {"tools": 0}, {"mode": "conversational"}])
def test_silent_when_not_agent_mode(kwargs: dict) -> None:
    """Tools disabled, no tools, or conversational mode log nothing."""
    bot = _agent_bot(_NoLoopClient(), **kwargs)
    bot._warn_if_client_lacks_tool_loop()
    assert _tool_loop_warnings(bot) == []


def test_silent_for_mock_client_without_bot_state() -> None:
    """A MagicMock client on a bot with no enable_tools: no warning, no AttributeError."""
    bot = object.__new__(_ConfigureTestBot)
    bot.logger = MagicMock()
    bot._llm = MagicMock()
    bot._warn_if_client_lacks_tool_loop()
    assert bot.logger.warning.call_count == 0


@pytest.mark.asyncio
async def test_configure_calls_warning_after_client_creation() -> None:
    """configure() warns once; a no-op second configure() with the same app adds none."""
    bot, app = _stub_bot(), _app()
    bot._create_llm_client = MagicMock(return_value=_NoLoopClient())
    bot.enable_tools = True
    bot.operation_mode = "adaptive"
    bot.tool_manager.tool_count.return_value = 1
    await bot.configure(app)
    await bot.configure(app)
    assert len(_tool_loop_warnings(bot)) == 1
