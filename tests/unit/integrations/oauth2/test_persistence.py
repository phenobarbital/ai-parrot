"""Unit tests for parrot.integrations.oauth2.persistence."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.oauth2.models import UserAgentToolkitRow, UsersIntegrationRow
from parrot.integrations.oauth2.persistence import (
    delete_user_agent_toolkits_by_provider,
    delete_users_integration,
    get_users_integration,
    list_user_agent_toolkits,
    upsert_user_agent_toolkit,
    upsert_users_integration,
)


@pytest.fixture
def sample_users_integration_row() -> UsersIntegrationRow:
    return UsersIntegrationRow(
        user_id="u1",
        provider="jira",
        account_id="a1",
        display_name="Test User",
        scopes=["read:jira-work"],
        connected_at=datetime.now(),
    )


@pytest.fixture
def sample_user_agent_toolkit_row() -> UserAgentToolkitRow:
    return UserAgentToolkitRow(
        user_id="u1",
        agent_id="agent1",
        toolkit_id="jira",
        provider="jira",
        enabled_at=datetime.now(),
    )


def _make_mock_db() -> tuple[MagicMock, AsyncMock]:
    """Return (mock_db_cls, mock_db_instance)."""
    mock_db_instance = AsyncMock()
    mock_db_cls = MagicMock()
    mock_db_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db_instance)
    mock_db_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_db_cls, mock_db_instance


class TestUsersIntegrationPersistence:
    """Tests for upsert / get / delete users_integrations operations."""

    @pytest.mark.asyncio
    async def test_upsert_calls_update_one(
        self, sample_users_integration_row: UsersIntegrationRow
    ) -> None:
        """upsert_users_integration calls db.update_one with upsert=True."""
        mock_db_cls, mock_db = _make_mock_db()
        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb", mock_db_cls
        ):
            await upsert_users_integration(sample_users_integration_row)
        mock_db.update_one.assert_called_once()
        call_kwargs = mock_db.update_one.call_args
        assert call_kwargs.kwargs.get("upsert") is True or (
            len(call_kwargs.args) > 3 and call_kwargs.args[3] is True
        ) or call_kwargs.args[-1] is True

    @pytest.mark.asyncio
    async def test_upsert_uses_correct_collection(
        self, sample_users_integration_row: UsersIntegrationRow
    ) -> None:
        """upsert_users_integration writes to users_integrations collection."""
        mock_db_cls, mock_db = _make_mock_db()
        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb", mock_db_cls
        ):
            await upsert_users_integration(sample_users_integration_row)
        collection_arg = mock_db.update_one.call_args.args[0]
        assert collection_arg == "users_integrations"

    @pytest.mark.asyncio
    async def test_get_returns_row_when_found(self) -> None:
        """get_users_integration returns UsersIntegrationRow when document found."""
        now = datetime.now()
        doc = {
            "user_id": "u1",
            "provider": "jira",
            "account_id": "a1",
            "display_name": "Test",
            "scopes": ["read:jira-work"],
            "connected_at": now,
            "channel": "web",
            "status": "active",
            "_id": "mongo-id",
        }
        mock_db_cls, mock_db = _make_mock_db()
        mock_db.read_one = AsyncMock(return_value=doc)
        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb", mock_db_cls
        ):
            result = await get_users_integration("u1", "jira")
        assert result is not None
        assert result.user_id == "u1"
        assert result.provider == "jira"

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self) -> None:
        """get_users_integration returns None when document not found."""
        mock_db_cls, mock_db = _make_mock_db()
        mock_db.read_one = AsyncMock(return_value=None)
        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb", mock_db_cls
        ):
            result = await get_users_integration("u_missing", "jira")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_calls_delete_many(self) -> None:
        """delete_users_integration calls db.delete_many."""
        mock_db_cls, mock_db = _make_mock_db()
        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb", mock_db_cls
        ):
            await delete_users_integration("u1", "jira")
        mock_db.delete_many.assert_called_once_with(
            "users_integrations", {"user_id": "u1", "provider": "jira"}
        )


class TestUserAgentToolkitPersistence:
    """Tests for upsert / list / cascade-delete user_agent_toolkits operations."""

    @pytest.mark.asyncio
    async def test_upsert_calls_update_one(
        self, sample_user_agent_toolkit_row: UserAgentToolkitRow
    ) -> None:
        """upsert_user_agent_toolkit calls db.update_one with upsert=True."""
        mock_db_cls, mock_db = _make_mock_db()
        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb", mock_db_cls
        ):
            await upsert_user_agent_toolkit(sample_user_agent_toolkit_row)
        mock_db.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_returns_rows(self) -> None:
        """list_user_agent_toolkits returns list of UserAgentToolkitRow."""
        now = datetime.now()
        docs = [
            {
                "user_id": "u1",
                "agent_id": "agent1",
                "toolkit_id": "jira",
                "provider": "jira",
                "enabled_at": now,
            }
        ]
        mock_db_cls, mock_db = _make_mock_db()
        mock_db.read = AsyncMock(return_value=docs)
        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb", mock_db_cls
        ):
            rows = await list_user_agent_toolkits("u1", "agent1")
        assert len(rows) == 1
        assert rows[0].toolkit_id == "jira"

    @pytest.mark.asyncio
    async def test_list_returns_empty_when_none(self) -> None:
        """list_user_agent_toolkits returns [] when no documents found."""
        mock_db_cls, mock_db = _make_mock_db()
        mock_db.read = AsyncMock(return_value=[])
        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb", mock_db_cls
        ):
            rows = await list_user_agent_toolkits("u_missing", "agent1")
        assert rows == []

    @pytest.mark.asyncio
    async def test_cascade_delete_calls_delete_many(self) -> None:
        """delete_user_agent_toolkits_by_provider calls db.delete_many."""
        mock_db_cls, mock_db = _make_mock_db()
        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb", mock_db_cls
        ):
            await delete_user_agent_toolkits_by_provider("u1", "jira")
        mock_db.delete_many.assert_called_once_with(
            "user_agent_toolkits", {"user_id": "u1", "provider": "jira"}
        )
