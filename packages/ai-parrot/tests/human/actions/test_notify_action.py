"""Unit tests for NotifyAction dispatcher.

TASK-1276 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.human.actions.notify import NotifyAction
from parrot.human.actions.backends import ActionBackendError, EmailBackendError
from parrot.human.models import EscalationActionType, EscalationTier, HumanInteraction


@pytest.fixture
def interaction():
    return HumanInteraction(question="Can you approve?")


def _tier(action_metadata):
    return EscalationTier(
        level=1,
        name="Notify",
        action_type=EscalationActionType.NOTIFY,
        action_metadata=action_metadata,
    )


class TestNotifyActionDispatcher:
    async def test_routes_to_email_by_kind(self, interaction):
        """kind=email routes to EmailBackend."""
        tier = _tier({"kind": "email", "to": ["ops@x.com"]})
        action = NotifyAction()

        mock_result = {"message": "[escalated:email] Notified ops@x.com.", "to": ["ops@x.com"], "status": "sent"}
        with patch.object(action, "_get_backend") as mock_get:
            mock_backend = AsyncMock()
            mock_backend.execute = AsyncMock(return_value=mock_result)
            mock_get.return_value = mock_backend
            result = await action.execute(interaction, tier)

        mock_get.assert_called_once_with("email")
        assert result["status"] == "sent"

    async def test_routes_to_email_by_legacy_channel_key(self, interaction):
        """Legacy channel=email routes to EmailBackend."""
        tier = _tier({"channel": "email", "to": ["ops@x.com"]})
        action = NotifyAction()

        with patch.object(action, "_get_backend") as mock_get:
            mock_backend = AsyncMock()
            mock_backend.execute = AsyncMock(
                return_value={"message": "ok", "status": "sent"}
            )
            mock_get.return_value = mock_backend
            await action.execute(interaction, tier)

        mock_get.assert_called_once_with("email")

    async def test_routes_to_webhook(self, interaction):
        """kind=webhook routes to WebhookBackend."""
        tier = _tier({"kind": "webhook", "url": "http://hook.example.com"})
        action = NotifyAction()

        with patch.object(action, "_get_backend") as mock_get:
            mock_backend = AsyncMock()
            mock_backend.execute = AsyncMock(
                return_value={"message": "link", "deep_link": "http://lc/1"}
            )
            mock_get.return_value = mock_backend
            await action.execute(interaction, tier)

        mock_get.assert_called_once_with("webhook")

    async def test_unknown_kind_raises_backend_error(self, interaction):
        """Unknown kind re-raises ActionBackendError so the manager advances."""
        tier = _tier({"kind": "sms"})
        action = NotifyAction()
        with pytest.raises(ActionBackendError, match="sms"):
            await action.execute(interaction, tier)

    async def test_backend_exception_reraised(self, interaction):
        """Backend failure is re-raised so the manager can advance the chain."""
        tier = _tier({"kind": "email", "to": []})
        action = NotifyAction()
        # EmailBackend raises EmailBackendError (an ActionBackendError) on empty 'to'
        with pytest.raises(EmailBackendError):
            await action.execute(interaction, tier)

    async def test_default_kind_is_email(self, interaction):
        """No kind or channel key defaults to email."""
        tier = _tier({})
        action = NotifyAction()

        with patch.object(action, "_get_backend") as mock_get:
            mock_backend = AsyncMock()
            mock_backend.execute = AsyncMock(
                return_value={"message": "ok", "status": "sent"}
            )
            mock_get.return_value = mock_backend
            await action.execute(interaction, tier)

        mock_get.assert_called_once_with("email")
