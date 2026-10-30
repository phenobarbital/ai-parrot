"""FEAT-752 TASK-4810 — Telegram wrapper: chip keyboard after a reply and the `sg` press handler."""

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aiogram")

from parrot.integrations.telegram.callbacks import CallbackContext, CallbackData, CallbackRegistry  # noqa: E402
from parrot.integrations.telegram.suggestion_buttons import (  # noqa: E402
    SUGGESTION_PREFIX,
    SuggestionButtonStore,
    build_suggestion_keyboard,
)
from parrot.models import Suggestion  # noqa: E402
from parrot.models.outputs import OutputMode  # noqa: E402


def _wrapper_class():
    module = pytest.importorskip("parrot.integrations.telegram.wrapper")
    return module.TelegramAgentWrapper


def _wrapper(*, enabled=True, authorized=True):
    wrapper = object.__new__(_wrapper_class())
    wrapper.logger = MagicMock()
    wrapper.config = SimpleNamespace(force_authentication=False)
    wrapper._suggestion_buttons = SuggestionButtonStore() if enabled else None
    wrapper._callback_registry = CallbackRegistry()
    wrapper._is_authorized = lambda chat_id: authorized
    wrapper._get_or_create_memory = lambda chat_id: "memory"
    wrapper._get_user_session = lambda query: SimpleNamespace(telegram_id=query.from_user.id, authenticated=True)
    wrapper._invoke_agent = AsyncMock(return_value=SimpleNamespace(suggestions=[]))
    wrapper._parse_response = lambda r: r
    wrapper._send_parsed_response = AsyncMock()
    wrapper.send_interactive_message = AsyncMock()
    return wrapper


def _message(chat_id=10):
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=1)


def _context(token, *, user_id=7, chat_id=10, message=True):
    query = SimpleNamespace(
        message=_message(chat_id) if message else None,
        from_user=SimpleNamespace(id=user_id),
    )
    return CallbackContext(
        prefix="sg",
        payload={"raw": token},
        chat_id=chat_id,
        user_id=user_id,
        message_id=1,
        raw_query=query,
    )


@pytest.mark.asyncio
async def test_press_replays_prompt_for_owner():
    wrapper = _wrapper()
    token = await wrapper._suggestion_buttons.put(prompt="Why?", output_mode="structured_table", chat_id=10, user_id=7)

    result = await wrapper._on_suggestion_press(_context(token))

    wrapper._invoke_agent.assert_awaited_once()
    args, kwargs = wrapper._invoke_agent.call_args
    assert args[1] == "Why?"
    assert kwargs["output_mode"] == OutputMode.STRUCTURED_TABLE
    assert kwargs["memory"] == "memory"
    wrapper._send_parsed_response.assert_awaited_once()
    assert result.reply_text is None  # no refusal


@pytest.mark.asyncio
async def test_press_unknown_mode_falls_back_to_telegram():
    wrapper = _wrapper()
    token = await wrapper._suggestion_buttons.put(prompt="Why?", output_mode="not-a-mode", chat_id=10, user_id=7)
    await wrapper._on_suggestion_press(_context(token))
    assert wrapper._invoke_agent.call_args.kwargs["output_mode"] == OutputMode.TELEGRAM

    token = await wrapper._suggestion_buttons.put(prompt="Why?", output_mode=None, chat_id=10, user_id=7)
    await wrapper._on_suggestion_press(_context(token))
    assert wrapper._invoke_agent.call_args.kwargs["output_mode"] == OutputMode.TELEGRAM


@pytest.mark.asyncio
async def test_press_refused_for_other_user_or_expired():
    wrapper = _wrapper()
    token = await wrapper._suggestion_buttons.put(prompt="Why?", output_mode=None, chat_id=10, user_id=7)

    other_user = await wrapper._on_suggestion_press(_context(token, user_id=8))
    other_chat = await wrapper._on_suggestion_press(_context(token, chat_id=11))
    unknown = await wrapper._on_suggestion_press(_context("sNOPE"))
    no_message = await wrapper._on_suggestion_press(_context(token, message=False))

    assert "not for you" in other_user.reply_text
    assert "not for you" in other_chat.reply_text
    assert "expired" in unknown.reply_text
    assert "expired" in no_message.reply_text
    wrapper._invoke_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_press_refused_when_chat_not_authorized():
    wrapper = _wrapper(authorized=False)
    token = await wrapper._suggestion_buttons.put(prompt="Why?", output_mode=None, chat_id=10, user_id=7)
    result = await wrapper._on_suggestion_press(_context(token))
    assert "not for you" in result.reply_text
    wrapper._invoke_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_press_with_feature_disabled_is_an_expiry_not_a_crash():
    wrapper = _wrapper(enabled=False)
    result = await wrapper._on_suggestion_press(_context("sABC"))
    assert "expired" in result.reply_text
    wrapper._invoke_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_press_sends_follow_up_keyboard_for_new_chips():
    wrapper = _wrapper()
    wrapper._invoke_agent = AsyncMock(
        return_value=SimpleNamespace(suggestions=[Suggestion(label="More", prompt="more")])
    )
    token = await wrapper._suggestion_buttons.put(prompt="Why?", output_mode=None, chat_id=10, user_id=7)
    await wrapper._on_suggestion_press(_context(token))
    wrapper.send_interactive_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_keyboard_sent_only_when_enabled_and_chips_present():
    chips = [
        Suggestion(label="A", prompt="a"),
        Suggestion(label="Explain this", prompt="Explain", kind="action", action="explain"),
    ]
    session = SimpleNamespace(telegram_id=7)

    disabled = _wrapper(enabled=False)
    await disabled._send_suggestion_keyboard(_message(), session, SimpleNamespace(suggestions=chips))
    disabled.send_interactive_message.assert_not_awaited()

    wrapper = _wrapper()
    await wrapper._send_suggestion_keyboard(_message(), session, SimpleNamespace(suggestions=[]))
    await wrapper._send_suggestion_keyboard(_message(), session, SimpleNamespace())  # legacy response object
    await wrapper._send_suggestion_keyboard(
        _message(), session, SimpleNamespace(suggestions=[chips[1]])  # only an action chip: nothing renderable
    )
    wrapper.send_interactive_message.assert_not_awaited()

    await wrapper._send_suggestion_keyboard(_message(), session, SimpleNamespace(suggestions=chips))
    wrapper.send_interactive_message.assert_awaited_once()
    chat_id, text, keyboard = wrapper.send_interactive_message.call_args.args
    assert chat_id == 10 and text == "💡 Follow-ups:"
    buttons = [b for row in keyboard["inline_keyboard"] for b in row]
    assert [b["text"] for b in buttons] == ["A"]  # the action chip is never rendered
    prefix, payload = CallbackData.decode(buttons[0]["callback_data"])
    assert prefix == "sg"
    stored = await wrapper._suggestion_buttons.get(payload["raw"])
    assert stored["user_id"] == 7 and stored["chat_id"] == 10


@pytest.mark.asyncio
async def test_keyboard_failure_never_raises():
    wrapper = _wrapper()
    wrapper.send_interactive_message = AsyncMock(side_effect=RuntimeError("telegram down"))
    await wrapper._send_suggestion_keyboard(
        _message(), SimpleNamespace(telegram_id=7), SimpleNamespace(suggestions=[Suggestion(label="A", prompt="a")])
    )
    wrapper.logger.warning.assert_called_once()


def test_sg_prefix_registered_before_handlers_and_independent_of_agent_callbacks():
    source = inspect.getsource(_wrapper_class().__init__)
    register = source.index("self._callback_registry.register(")
    assert source.index("SuggestionButtonStore(") < register
    assert register < source.index("self._register_handlers()")
    assert 'getattr(config, "suggestion_buttons", False)' in source
    # registered before (and independently of) the agent's own @telegram_callback discovery
    assert register < source.index("discover_from_agent")


def test_registry_routes_sg_buttons_to_the_press_handler():
    wrapper = _wrapper()
    wrapper._callback_registry.register(SUGGESTION_PREFIX, wrapper._on_suggestion_press, "x")
    matched = wrapper._callback_registry.match("sg:sAbCdEfGhIj1")
    assert matched is not None
    meta, payload = matched
    assert meta.prefix == "sg" and payload == {"raw": "sAbCdEfGhIj1"}


@pytest.mark.asyncio
async def test_build_keyboard_helper_used_by_wrapper_matches_store():
    store = SuggestionButtonStore()
    kb = await build_suggestion_keyboard([Suggestion(label="A", prompt="a")], store, chat_id=1, user_id=2)
    assert kb["inline_keyboard"][0][0]["callback_data"].startswith("sg:")


def test_handle_message_sends_keyboard_after_reply_source():
    source = inspect.getsource(_wrapper_class().handle_message)
    assert source.count("_send_suggestion_keyboard(") == 1
    assert source.index("_send_parsed_response(message, parsed)") < source.index("_send_suggestion_keyboard(")


@pytest.mark.asyncio
async def test_press_refused_when_session_no_longer_authenticated():
    """A token outlives a logout/expired session; a press must not run the agent for a signed-out user."""
    wrapper = _wrapper()
    wrapper.config = SimpleNamespace(force_authentication=True)
    wrapper._get_user_session = lambda query: SimpleNamespace(telegram_id=query.from_user.id, authenticated=False)
    token = await wrapper._suggestion_buttons.put(prompt="Why?", output_mode=None, chat_id=10, user_id=7)

    result = await wrapper._on_suggestion_press(_context(token))

    assert "/login" in result.reply_text
    wrapper._invoke_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_press_allowed_when_forced_auth_and_session_authenticated():
    wrapper = _wrapper()
    wrapper.config = SimpleNamespace(force_authentication=True)
    token = await wrapper._suggestion_buttons.put(prompt="Why?", output_mode=None, chat_id=10, user_id=7)
    result = await wrapper._on_suggestion_press(_context(token))
    wrapper._invoke_agent.assert_awaited_once()
    assert result.reply_text is None


@pytest.mark.asyncio
async def test_unauthenticated_press_allowed_when_auth_not_forced():
    wrapper = _wrapper()
    wrapper._get_user_session = lambda query: SimpleNamespace(telegram_id=query.from_user.id, authenticated=False)
    token = await wrapper._suggestion_buttons.put(prompt="Why?", output_mode=None, chat_id=10, user_id=7)
    await wrapper._on_suggestion_press(_context(token))
    wrapper._invoke_agent.assert_awaited_once()
