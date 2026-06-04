"""Unit tests for TicketAction dispatcher.

TASK-1276 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from parrot.human.actions.ticket import TicketAction
from parrot.human.actions.backends import ActionBackendError
from parrot.human.models import EscalationActionType, EscalationTier, HumanInteraction


@pytest.fixture
def interaction():
    return HumanInteraction(question="Need a support ticket created.")


def _tier(action_metadata):
    return EscalationTier(
        level=2,
        name="Ticket",
        action_type=EscalationActionType.TICKET,
        action_metadata=action_metadata,
    )


class TestTicketActionDispatcher:
    async def test_routes_to_zammad_by_kind(self, interaction):
        """kind=zammad routes to ZammadBackend."""
        tier = _tier({"kind": "zammad", "queue": "OPS"})
        action = TicketAction()

        with patch.object(action, "_get_backend") as mock_get:
            mock_backend = AsyncMock()
            mock_backend.execute = AsyncMock(
                return_value={"message": "Ticket #1 opened.", "ticket_id": 1, "url": "http://z/1"}
            )
            mock_get.return_value = mock_backend
            result = await action.execute(interaction, tier)

        mock_get.assert_called_once_with("zammad")
        assert result["ticket_id"] == 1

    async def test_legacy_jira_platform_logs_warning_and_routes_zammad(self, interaction, caplog):
        """platform=jira logs a deprecation warning and routes to Zammad."""
        import logging
        tier = _tier({"platform": "jira", "project": "OPS"})
        action = TicketAction()

        with patch.object(action, "_get_backend") as mock_get:
            mock_backend = AsyncMock()
            mock_backend.execute = AsyncMock(
                return_value={"message": "Ticket #42 opened.", "ticket_id": 42, "url": "http://z/42"}
            )
            mock_get.return_value = mock_backend
            with caplog.at_level(logging.WARNING, logger="parrot.human.actions.ticket"):
                await action.execute(interaction, tier)

        mock_get.assert_called_once_with("zammad")
        assert any("jira" in r.message.lower() for r in caplog.records)

    async def test_unknown_kind_raises_backend_error(self, interaction):
        """Unknown kind re-raises ActionBackendError so the manager advances."""
        tier = _tier({"kind": "zendesk"})
        action = TicketAction()
        with pytest.raises(ActionBackendError, match="zendesk"):
            await action.execute(interaction, tier)

    async def test_default_kind_is_zammad(self, interaction):
        """No kind or platform key defaults to zammad."""
        tier = _tier({})
        action = TicketAction()

        with patch.object(action, "_get_backend") as mock_get:
            mock_backend = AsyncMock()
            mock_backend.execute = AsyncMock(
                return_value={"message": "done", "ticket_id": 99, "url": "http://z/99"}
            )
            mock_get.return_value = mock_backend
            await action.execute(interaction, tier)

        mock_get.assert_called_once_with("zammad")
