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
