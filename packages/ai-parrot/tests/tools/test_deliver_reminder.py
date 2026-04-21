"""Unit tests for deliver_reminder — FEAT-115 / TASK-819.

Verifies that the module-scope coroutine forwards the correct arguments to
NotificationMixin.send_notification and prepends the ⏰ Recordatorio prefix.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.reminder import deliver_reminder


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

        # Message must start with the ⏰ prefix
        assert call_kwargs["message"].startswith(
            f"⏰ *Recordatorio* (programado {requested_at}):\n\n"
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
