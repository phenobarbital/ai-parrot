"""Unit tests for parrot.handlers.mcp_persistence — MCPPersistenceService."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from parrot.handlers.mcp_persistence import MCPPersistenceService
from parrot.mcp.registry import UserMCPServerConfig


@pytest.fixture
def service() -> MCPPersistenceService:
    """MCPPersistenceService instance for tests."""
    return MCPPersistenceService()


@pytest.fixture
def sample_config() -> UserMCPServerConfig:
    """Sample UserMCPServerConfig for perplexity."""
    return UserMCPServerConfig(
        server_name="perplexity",
        agent_id="test-agent",
        user_id="user-123",
        params={},
        vault_credential_name="mcp_perplexity_test-agent",
        active=True,
    )


def _make_mock_db(read_one_return=None, read_return=None):
    """Build a mock DocumentDb context manager."""
    mock_db = AsyncMock()
    mock_db.read_one.return_value = read_one_return
    mock_db.read.return_value = read_return or []
    mock_db.write.return_value = AsyncMock()
    mock_db.update_one.return_value = AsyncMock()

    # Build the context manager wrapper
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, mock_db


class TestMCPPersistenceService:
    """Tests for MCPPersistenceService."""

    @pytest.mark.asyncio
    async def test_save_config_uses_atomic_upsert(
        self, service: MCPPersistenceService, sample_config: UserMCPServerConfig
    ) -> None:
        """save_user_mcp_config uses update_one with upsert=True (atomic)."""
        cm, mock_db = _make_mock_db(read_one_return=None)

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            await service.save_user_mcp_config(sample_config)

        mock_db.update_one.assert_called_once()
        call_args = mock_db.update_one.call_args
        assert call_args[1].get("upsert") is True or (
            len(call_args[0]) > 3 and call_args[0][3] is True
        )
        mock_db.read_one.assert_not_called()
        mock_db.write.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_config_sets_timestamps(
        self, service: MCPPersistenceService, sample_config: UserMCPServerConfig
    ) -> None:
        """save passes $set.updated_at and $setOnInsert.created_at."""
        cm, mock_db = _make_mock_db(read_one_return=None)

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            await service.save_user_mcp_config(sample_config)

        call_args = mock_db.update_one.call_args
        update_data = call_args[0][2]
        assert "$set" in update_data
        assert "updated_at" in update_data["$set"]
        assert "$setOnInsert" in update_data
        assert "created_at" in update_data["$setOnInsert"]

    @pytest.mark.asyncio
    async def test_save_config_update_data_has_set(
        self, service: MCPPersistenceService, sample_config: UserMCPServerConfig
    ) -> None:
        """Upsert uses $set operator with params, vault_credential_name, active."""
        cm, mock_db = _make_mock_db(read_one_return=None)

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            await service.save_user_mcp_config(sample_config)

        call_args = mock_db.update_one.call_args
        update_data = call_args[0][2]
        set_data = update_data["$set"]
        assert "params" in set_data
        assert "vault_credential_name" in set_data
        assert "active" in set_data

    @pytest.mark.asyncio
    async def test_load_returns_active_only(
        self, service: MCPPersistenceService
    ) -> None:
        """load_user_mcp_configs returns only active=True configs."""
        active_doc = {
            "server_name": "perplexity",
            "agent_id": "a",
            "user_id": "u",
            "params": {},
            "active": True,
            "vault_credential_name": None,
        }
        cm, mock_db = _make_mock_db(read_return=[active_doc])

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            configs = await service.load_user_mcp_configs("u", "a")

        assert len(configs) == 1
        assert configs[0].server_name == "perplexity"
        assert configs[0].active is True

    @pytest.mark.asyncio
    async def test_load_empty_result(self, service: MCPPersistenceService) -> None:
        """load_user_mcp_configs returns empty list when no configs exist."""
        cm, mock_db = _make_mock_db(read_return=[])

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            configs = await service.load_user_mcp_configs("u", "a")

        assert configs == []

    @pytest.mark.asyncio
    async def test_load_queries_with_active_true(
        self, service: MCPPersistenceService
    ) -> None:
        """load_user_mcp_configs queries DocumentDB with active=True filter."""
        cm, mock_db = _make_mock_db(read_return=[])

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            await service.load_user_mcp_configs("user-1", "agent-1")

        call_args = mock_db.read.call_args
        query = call_args[0][1]  # positional: (collection, query)
        assert query["active"] is True
        assert query["user_id"] == "user-1"
        assert query["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_load_returns_config_objects(
        self, service: MCPPersistenceService
    ) -> None:
        """load_user_mcp_configs converts dicts to UserMCPServerConfig objects."""
        docs = [
            {
                "server_name": "fireflies",
                "agent_id": "a1",
                "user_id": "u1",
                "params": {"region": "us"},
                "vault_credential_name": "mcp_fireflies_a1",
                "active": True,
            }
        ]
        cm, mock_db = _make_mock_db(read_return=docs)

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            configs = await service.load_user_mcp_configs("u1", "a1")

        assert len(configs) == 1
        assert isinstance(configs[0], UserMCPServerConfig)
        assert configs[0].vault_credential_name == "mcp_fireflies_a1"

    @pytest.mark.asyncio
    async def test_remove_soft_deletes_and_returns_true(
        self, service: MCPPersistenceService
    ) -> None:
        """remove_user_mcp_config soft-deletes document, returns True."""
        existing_doc = {"_id": "existing", "active": True}
        cm, mock_db = _make_mock_db(read_one_return=existing_doc)

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            result = await service.remove_user_mcp_config("u", "a", "perplexity")

        assert result is True
        mock_db.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_sets_active_false(
        self, service: MCPPersistenceService
    ) -> None:
        """remove_user_mcp_config sets active=False in the update."""
        existing_doc = {"_id": "existing", "active": True}
        cm, mock_db = _make_mock_db(read_one_return=existing_doc)

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            await service.remove_user_mcp_config("u", "a", "perplexity")

        call_args = mock_db.update_one.call_args
        update_data = call_args[0][2]
        assert update_data["$set"]["active"] is False

    @pytest.mark.asyncio
    async def test_remove_nonexistent_returns_false(
        self, service: MCPPersistenceService
    ) -> None:
        """remove_user_mcp_config returns False when no document found."""
        cm, mock_db = _make_mock_db(read_one_return=None)

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            result = await service.remove_user_mcp_config("u", "a", "nonexistent")

        assert result is False
        mock_db.update_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_does_not_hard_delete(
        self, service: MCPPersistenceService
    ) -> None:
        """remove_user_mcp_config never calls delete (soft-delete only)."""
        existing_doc = {"_id": "existing", "active": True}
        cm, mock_db = _make_mock_db(read_one_return=existing_doc)

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            await service.remove_user_mcp_config("u", "a", "perplexity")

        mock_db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_skips_malformed_docs(
        self, service: MCPPersistenceService
    ) -> None:
        """load_user_mcp_configs silently skips malformed documents."""
        docs = [
            # Missing required fields — should be skipped
            {"active": True},
            # Valid doc
            {
                "server_name": "perplexity",
                "agent_id": "a",
                "user_id": "u",
                "params": {},
                "active": True,
            },
        ]
        cm, mock_db = _make_mock_db(read_return=docs)

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            configs = await service.load_user_mcp_configs("u", "a")

        # Only the valid doc is returned
        assert len(configs) == 1
        assert configs[0].server_name == "perplexity"

    @pytest.mark.asyncio
    async def test_save_scopes_query_correctly(
        self, service: MCPPersistenceService, sample_config: UserMCPServerConfig
    ) -> None:
        """save_user_mcp_config scopes upsert by user_id, agent_id, server_name."""
        cm, mock_db = _make_mock_db(read_one_return=None)

        with patch("parrot.handlers.mcp_persistence.DocumentDb", return_value=cm):
            await service.save_user_mcp_config(sample_config)

        call_args = mock_db.update_one.call_args
        query = call_args[0][1]
        assert query["user_id"] == sample_config.user_id
        assert query["agent_id"] == sample_config.agent_id
        assert query["server_name"] == sample_config.server_name
