"""Unit tests for deliver_reminder — FEAT-115 / TASK-819.

Verifies that the module-scope coroutine forwards the correct arguments to
NotificationMixin.send_notification and prepends the ⏰ Recordatorio prefix.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.reminder import (
    deliver_reminder,
    register_telegram_bot,
    unregister_telegram_bot,
)


async def test_deliver_reminder_forwards_to_send_notification():
    """deliver_reminder patches _notifier and checks forwarded args."""
    requested_at = "2026-04-22T12:00:00+00:00"

    with patch("parrot.tools.reminder._notifier") as mock_notifier:
        mock_notifier.send_notification = AsyncMock(return_value={})

        await deliver_reminder(
            provider="telegram",
            recipients=[987654321],
            message="call the developer",
            requested_by="user-123",
            requested_at=requested_at,
        )

        mock_notifier.send_notification.assert_awaited_once()
        call_kwargs = mock_notifier.send_notification.call_args.kwargs

        # Message must start with the ⏰ prefix. Telegram is rendered by the
        # notify provider with parse_mode=html, so the prefix uses HTML tags
        # (matching parrot.tools.reminder.deliver_reminder's shipped format).
        assert call_kwargs["message"].startswith(
            f"⏰ <b>Reminder</b> (scheduled {requested_at}):\n\n"
        )
        # Message must end with the original text
        assert call_kwargs["message"].endswith("call the developer")

        # Other fields pass through unchanged
        assert call_kwargs["recipients"] == [987654321]
        assert call_kwargs["provider"] == "telegram"


async def test_deliver_reminder_prefix_contains_requested_at():
    """The ⏰ prefix embeds the requested_at timestamp verbatim."""
    ts = "2025-12-31T23:59:00+00:00"

    with patch("parrot.tools.reminder._notifier") as mock_notifier:
        mock_notifier.send_notification = AsyncMock(return_value={})

        await deliver_reminder(
            provider="email",
            recipients=["user@example.com"],
            message="year-end check",
            requested_by="user-42",
            requested_at=ts,
        )

        msg = mock_notifier.send_notification.call_args.kwargs["message"]
        assert ts in msg
        assert "year-end check" in msg


async def test_deliver_reminder_routes_to_registered_bot_token():
    """A telegram reminder whose bot_id is registered delivers through that
    bot's token (passed as provider_options) — not the env default bot."""
    register_telegram_bot("123456", "123456:SECRET-TOKEN")
    try:
        with patch("parrot.tools.reminder._notifier") as mock_notifier:
            mock_notifier.send_notification = AsyncMock(return_value={})

            await deliver_reminder(
                provider="telegram",
                recipients=[-1001234567],
                message="standup in 5",
                requested_by="user-123",
                requested_at="2026-04-22T12:00:00+00:00",
                bot_id="123456",
            )

            call_kwargs = mock_notifier.send_notification.call_args.kwargs
            assert call_kwargs["provider_options"] == {
                "bot_token": "123456:SECRET-TOKEN"
            }
            assert call_kwargs["recipients"] == [-1001234567]
    finally:
        unregister_telegram_bot("123456")


async def test_deliver_reminder_unregistered_bot_falls_back_to_env():
    """When bot_id is not registered, provider_options is None so the notify
    provider uses the TELEGRAM_BOT_TOKEN env default (legacy behaviour)."""
    unregister_telegram_bot("999999")  # ensure absent
    with patch("parrot.tools.reminder._notifier") as mock_notifier:
        mock_notifier.send_notification = AsyncMock(return_value={})

        await deliver_reminder(
            provider="telegram",
            recipients=[987654321],
            message="ping",
            requested_by="user-123",
            requested_at="2026-04-22T12:00:00+00:00",
            bot_id="999999",
        )

        call_kwargs = mock_notifier.send_notification.call_args.kwargs
        assert call_kwargs["provider_options"] is None


async def test_deliver_reminder_without_bot_id_is_backward_compatible():
    """Omitting bot_id (pre-existing jobs) → provider_options is None."""
    with patch("parrot.tools.reminder._notifier") as mock_notifier:
        mock_notifier.send_notification = AsyncMock(return_value={})

        await deliver_reminder(
            provider="telegram",
            recipients=[987654321],
            message="legacy",
            requested_by="user-123",
            requested_at="2026-04-22T12:00:00+00:00",
        )

        call_kwargs = mock_notifier.send_notification.call_args.kwargs
        assert call_kwargs["provider_options"] is None
