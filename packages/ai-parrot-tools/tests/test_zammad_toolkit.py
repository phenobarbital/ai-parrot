"""Unit tests for parrot_tools.zammad.ZammadToolkit."""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import pytest

from parrot_tools.zammad import ZammadToolkit


@pytest.fixture
def toolkit():
    """Return a ZammadToolkit configured with explicit kwargs."""
    return ZammadToolkit(
        instance_url="https://zammad.example.com",
        token="test-token",
        default_group="Support",
    )


class TestZammadToolkitRegistration:
    """Tests for tool discovery, prefixing, and exclusion."""

    def test_tool_prefix(self, toolkit):
        names = toolkit.list_tool_names()
        assert names, "Expected at least one registered tool"
        assert all(n.startswith("zammad_") for n in names)

    def test_delete_excluded(self, toolkit):
        names = toolkit.list_tool_names()
        assert "zammad_delete_ticket" not in names

    def test_expected_tools_present(self, toolkit):
        names = set(toolkit.list_tool_names())
        expected = {
            "zammad_create_ticket", "zammad_get_ticket", "zammad_list_tickets",
            "zammad_update_ticket", "zammad_close_ticket", "zammad_search_tickets",
            "zammad_get_user", "zammad_search_users", "zammad_create_user",
            "zammad_get_articles", "zammad_get_attachment",
        }
        assert expected.issubset(names)

    def test_toolkit_delete_excluded(self, toolkit):
        """Spec §4: zammad_delete_ticket must not be a registered tool."""
        names = toolkit.list_tool_names()
        assert "zammad_delete_ticket" not in names
        # The underlying method remains directly callable (not tool-exposed).
        assert hasattr(toolkit, "delete_ticket")


def test_zammad_in_registry():
    """Spec §4 / TASK-1704: TOOL_REGISTRY resolves the zammad entry."""
    from parrot_tools import TOOL_REGISTRY

    assert "zammad" in TOOL_REGISTRY
    assert TOOL_REGISTRY["zammad"] == "parrot_tools.zammad.ZammadToolkit"


class TestZammadToolkitLifecycle:
    """Tests for start()/stop() lifecycle wiring the interface."""

    @pytest.mark.asyncio
    async def test_start_stop(self, toolkit):
        with patch("parrot_tools.zammad.ZammadInterface") as MockInterface:
            mock_instance = AsyncMock()
            MockInterface.return_value = mock_instance
            await toolkit.start()
            assert toolkit._interface is not None
            await toolkit.stop()
            mock_instance.close.assert_called_once()


class TestZammadToolkitMethods:
    """Tests for individual tool methods delegating to the interface."""

    @pytest.mark.asyncio
    async def test_create_ticket_delegates(self, toolkit):
        toolkit._interface = AsyncMock()
        toolkit._interface.create_ticket.return_value = {"id": 1}

        result = await toolkit.create_ticket(
            title="Help",
            group="Support",
            customer="customer@example.com",
            article_body="I need help",
        )

        assert result == {"id": 1}
        toolkit._interface.create_ticket.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_ticket_sets_state(self, toolkit):
        toolkit._interface = AsyncMock()
        toolkit._interface.update_ticket.return_value = {"id": 5, "state_id": 4}

        result = await toolkit.close_ticket(ticket_id=5)

        assert result["state_id"] == 4
        call_args = toolkit._interface.update_ticket.call_args[0][0]
        assert call_args.ticket_id == 5
        assert call_args.state_id == toolkit._closed_state_id

    @pytest.mark.asyncio
    async def test_delete_ticket_not_a_registered_tool_but_callable(self, toolkit):
        toolkit._interface = AsyncMock()

        result = await toolkit.delete_ticket(ticket_id=7)

        assert result == {"ticket_id": 7, "deleted": True}
        toolkit._interface.delete_ticket.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_attachment_returns_dict(self, toolkit):
        toolkit._interface = AsyncMock()
        toolkit._interface.get_attachment.return_value = (
            b"hello",
            "/tmp/zammad_attachments/report.txt",
        )

        result = await toolkit.get_attachment(ticket_id=1, article_id=2, attachment_id=3)

        assert result["file_path"] == "/tmp/zammad_attachments/report.txt"
        assert result["filename"] == "report.txt"
        assert result["base64"] == base64.b64encode(b"hello").decode("ascii")
        assert result["mime_type"] == "text/plain"

    @pytest.mark.asyncio
    async def test_toolkit_attachment_returns_dict(self, toolkit):
        """Spec §4: get_attachment must return file_path/base64/mime_type/filename."""
        toolkit._interface = AsyncMock()
        toolkit._interface.get_attachment.return_value = (
            b"%PDF-1.4 fake",
            "/tmp/zammad_attachments/invoice.pdf",
        )

        result = await toolkit.get_attachment(ticket_id=10, article_id=20, attachment_id=30)

        assert set(result.keys()) == {"file_path", "base64", "mime_type", "filename"}
        assert result["filename"] == "invoice.pdf"
        assert result["mime_type"] == "application/pdf"

    @pytest.mark.asyncio
    async def test_search_users_delegates(self, toolkit):
        toolkit._interface = AsyncMock()
        toolkit._interface.search_users.return_value = [{"id": 5, "login": "jane@example.com"}]

        result = await toolkit.search_users("jane")

        assert result == [{"id": 5, "login": "jane@example.com"}]
        toolkit._interface.search_users.assert_called_once_with("jane")
