"""Redis-backed per-user MCP configuration tests (FEAT-878)."""

import pytest

from parrot.handlers import mcp_persistence
from parrot.handlers.mcp_persistence import MCPPersistenceService
from parrot.mcp.registry import UserMCPServerConfig
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def svc(monkeypatch):
    """Provide a service configured for an isolated Redis test namespace."""
    monkeypatch.delenv("MCP_CONFIGS_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr(mcp_persistence, "_REDIS_STORE", None)
    async with redis_test_settings(monkeypatch):
        yield MCPPersistenceService()


async def test_mcp_configs_redis_soft_delete(svc):
    """A soft-deleted configuration is hidden, then reactivated without a new creation time."""
    config = UserMCPServerConfig(server_name="perplexity", agent_id="a1", user_id="35", params={"m": 1})
    await svc.save_user_mcp_config(config)
    initial = await svc.load_user_mcp_configs("35", "a1")
    assert len(initial) == 1
    assert initial[0].created_at is not None

    assert await svc.remove_user_mcp_config("35", "a1", "perplexity") is True
    assert await svc.load_user_mcp_configs("35", "a1") == []

    await svc.save_user_mcp_config(config)
    restored = await svc.load_user_mcp_configs("35", "a1")
    assert len(restored) == 1
    assert restored[0].active is True
    assert restored[0].created_at == initial[0].created_at


async def test_remove_absent_returns_false(svc):
    """Removing a non-existent Redis configuration does not create it."""
    assert await svc.remove_user_mcp_config("35", "a1", "missing") is False
    assert await svc.load_user_mcp_configs("35", "a1") == []
