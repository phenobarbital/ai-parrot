"""FEAT-776 AC-17: Telegram-only startup registers the generic notifier once."""

import pytest

from parrot.auth.oauth2.events import ChannelNotifierRegistry
from parrot.integrations.manager import _register_channel_notifiers
from parrot.integrations.telegram.connection_notifier import TelegramConnectionNotifier


@pytest.mark.asyncio
async def test_telegram_only_startup_registers_notifier() -> None:
    """Telegram startup creates one generic notifier and accepts repeated attachments."""
    ChannelNotifierRegistry._reset()
    app: dict[str, object] = {}
    try:
        first_registry = _register_channel_notifiers(app)
        second_registry = _register_channel_notifiers(app)

        notifier = app["telegram_connection_notifier"]
        assert isinstance(notifier, TelegramConnectionNotifier)
        assert first_registry is second_registry
        assert first_registry.get("telegram") is notifier

        first_bot = object()
        second_bot = object()
        notifier.attach("bot-1", first_bot)
        notifier.attach("bot-2", second_bot)
        assert notifier._bots == {"bot-1": first_bot, "bot-2": second_bot}
    finally:
        ChannelNotifierRegistry._reset()


@pytest.mark.asyncio
async def test_attach_telegram_wrapper_wires_notifier_hooks_and_coordinator() -> None:
    """Both startup paths bind a wrapper built before the notifier: bot attached, hook and coordinator registered."""
    from unittest.mock import MagicMock

    from parrot.integrations.manager import attach_telegram_wrapper

    ChannelNotifierRegistry._reset()
    app: dict[str, object] = {}
    wrapper = MagicMock(_bot_id="bot-1")
    bot = object()
    try:
        attach_telegram_wrapper(app, wrapper, bot)
        attach_telegram_wrapper(app, wrapper, bot)  # repeated startup is harmless

        notifier = app["telegram_connection_notifier"]
        assert notifier._bots == {"bot-1": bot}
        assert wrapper._register_jira_session_hook.call_count == 2
        assert wrapper._attach_login_coordinator.call_count == 2
        assert "connection_event_publisher" in app
    finally:
        ChannelNotifierRegistry._reset()
