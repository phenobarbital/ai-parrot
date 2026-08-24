"""Unit tests for TASK-2377 — telegram_chat_scope in agent command handlers.

Verifies that the inner ``agent_cmd_handler`` built by
``TelegramAgentWrapper._register_agent_commands`` enters
``telegram_chat_scope(chat_id)`` around the decorated method invocation and
the response parsing/sending, for all three ``parse_mode`` variants, and that
the contextvar is reset both on normal return and on exception.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.integrations.telegram.context import (
    current_telegram_chat_id,
    get_current_telegram_chat_id,
)


def _make_wrapper(monkeypatch, method):
    """Build a minimal TelegramAgentWrapper wired to a single agent command.

    Bypasses ``__init__`` (no real aiogram Router / Redis init needed) and
    stubs the collaborators the handler body touches: authorization,
    response parsing, and response sending.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        method: The coroutine function to register as the command's target.

    Returns:
        Tuple of ``(wrapper, router_mock)``. The registered handler can be
        retrieved from ``router_mock.message.register.call_args_list``.
    """
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.logger = MagicMock()
    wrapper.config = MagicMock()
    wrapper.config.allowed_chat_ids = None  # fail-open
    wrapper.router = MagicMock()
    wrapper._agent_commands = [
        {
            "command": "note",
            "method": method,
            "method_name": "arm_note_mode",
            "parse_mode": "raw",
        }
    ]

    async def _typing_indicator(chat_id):
        # Real implementation loops until cancelled; a no-op coroutine is
        # cancel-safe and keeps the test synchronous.
        return None

    wrapper._typing_indicator = _typing_indicator
    wrapper._parse_response = lambda response: response
    wrapper._send_parsed_response = AsyncMock()

    wrapper._register_agent_commands()
    return wrapper


def _make_message(chat_id: int, text: str = "/note") -> MagicMock:
    """Create a mock aiogram Message."""
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def _registered_handler(wrapper) -> callable:
    """Extract the inner handler function passed to ``router.message.register``."""
    call = wrapper.router.message.register.call_args
    return call.args[0]


class TestAgentCommandChatScope:
    """AC: the decorated method resolves the invoking chat id during the call."""

    @pytest.mark.asyncio
    async def test_handler_sees_chat_id(self, monkeypatch):
        seen = {}

        async def _cmd(raw_args: str) -> str:
            seen["chat"] = get_current_telegram_chat_id()
            return "ok"

        wrapper = _make_wrapper(monkeypatch, _cmd)
        handler = _registered_handler(wrapper)

        assert current_telegram_chat_id.get() is None
        await handler(_make_message(chat_id=12345))

        assert seen["chat"] == "12345"  # str, not int

    @pytest.mark.asyncio
    async def test_scope_resets_after_return(self, monkeypatch):
        async def _cmd(raw_args: str) -> str:
            return "ok"

        wrapper = _make_wrapper(monkeypatch, _cmd)
        handler = _registered_handler(wrapper)

        await handler(_make_message(chat_id=12345))

        assert current_telegram_chat_id.get() is None

    @pytest.mark.asyncio
    async def test_scope_resets_on_exception(self, monkeypatch):
        async def _cmd(raw_args: str) -> str:
            raise RuntimeError("boom")

        wrapper = _make_wrapper(monkeypatch, _cmd)
        handler = _registered_handler(wrapper)

        message = _make_message(chat_id=12345)
        await handler(message)  # handler swallows the exception, replies with an error

        assert current_telegram_chat_id.get() is None
        message.answer.assert_awaited()
        assert "Error" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("parse_mode", ["keyword", "positional", "raw"])
    async def test_all_parse_modes_scoped(self, monkeypatch, parse_mode):
        seen = {}

        async def _cmd(*args, **kwargs) -> str:
            seen["chat"] = get_current_telegram_chat_id()
            return "ok"

        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.logger = MagicMock()
        wrapper.config = MagicMock()
        wrapper.config.allowed_chat_ids = None
        wrapper.router = MagicMock()
        wrapper._agent_commands = [
            {
                "command": "note",
                "method": _cmd,
                "method_name": "arm_note_mode",
                "parse_mode": parse_mode,
            }
        ]

        async def _typing_indicator(chat_id):
            return None

        wrapper._typing_indicator = _typing_indicator
        wrapper._parse_response = lambda response: response
        wrapper._send_parsed_response = AsyncMock()
        wrapper._register_agent_commands()

        handler = _registered_handler(wrapper)
        await handler(_make_message(chat_id=999, text="/note a=1"))

        assert seen["chat"] == "999"


class TestExistingAgentCommandsUnaffected:
    """AC: commands that ignore chat scope behave identically."""

    @pytest.mark.asyncio
    async def test_command_ignoring_scope_still_works(self, monkeypatch):
        async def _cmd(raw_args: str) -> str:
            return f"echo:{raw_args}"

        wrapper = _make_wrapper(monkeypatch, _cmd)
        handler = _registered_handler(wrapper)

        await handler(_make_message(chat_id=12345, text="/note hello"))

        wrapper._send_parsed_response.assert_awaited_once()
        _sent_message, sent_parsed = wrapper._send_parsed_response.call_args[0]
        assert sent_parsed == "echo:hello"

    @pytest.mark.asyncio
    async def test_unauthorized_chat_short_circuits_before_scope(self, monkeypatch):
        seen = {"called": False}

        async def _cmd(raw_args: str) -> str:
            seen["called"] = True
            return "ok"

        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.logger = MagicMock()
        wrapper.config = MagicMock()
        wrapper.config.allowed_chat_ids = [1]  # 12345 not authorized
        wrapper.router = MagicMock()
        wrapper._agent_commands = [
            {
                "command": "note",
                "method": _cmd,
                "method_name": "arm_note_mode",
                "parse_mode": "raw",
            }
        ]
        wrapper._parse_response = lambda response: response
        wrapper._send_parsed_response = AsyncMock()
        wrapper._register_agent_commands()

        handler = _registered_handler(wrapper)
        message = _make_message(chat_id=12345)
        await handler(message)

        assert seen["called"] is False
        message.answer.assert_awaited_once()
        assert "not authorized" in message.answer.call_args[0][0]
