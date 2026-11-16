"""AC8: Redis request paths never contact DocumentDB."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.handlers.agent import AgentTalk
from parrot.handlers.mcp_persistence import MCPPersistenceService
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride
from parrot.handlers.user_objects import UserObjectsHandler
from parrot.interfaces.documentdb import DocumentDb
from parrot.mcp.registry import UserMCPServerConfig
from parrot.userstore.testing import redis_test_settings


class Session(dict):
    """Mapping session with the identity attributes used by request handlers."""

    user_id = "u1"


@pytest.fixture
async def no_mongo(monkeypatch: pytest.MonkeyPatch):
    """Select Redis globally and make every DocumentDB connection fatal."""
    monkeypatch.setenv("PARROT_USER_STORE", "redis")
    monkeypatch.setenv("DOCUMENTDB_HOSTNAME", "127.0.0.1")
    monkeypatch.setenv("DOCUMENTDB_PORT", "1")

    async def forbidden(_self: DocumentDb) -> None:
        raise AssertionError("DocumentDB contacted with PARROT_USER_STORE=redis")

    monkeypatch.setattr(DocumentDb, "documentdb_connect", forbidden)
    async with redis_test_settings(monkeypatch):
        yield


@pytest.mark.asyncio
async def test_oauth_hydration_without_mongodb(no_mongo: None) -> None:
    """An empty Redis integration store produces no hydrated manager."""
    handler = UserObjectsHandler.__new__(UserObjectsHandler)
    handler.logger = logging.getLogger(__name__)
    session: dict[str, object] = {}
    assert await handler._hydrate_oauth_toolkits("u1", "agent", "tools", session) is None
    assert "tools" not in session


@pytest.mark.asyncio
async def test_toolkit_overrides_without_mongodb(no_mongo: None) -> None:
    """A Redis override is consumed by the request-path method."""
    await ToolkitConfigService().save(UserToolkitOverride(user_id="u1", agent_id="agent", slug="missing"))
    talk = AgentTalk.__new__(AgentTalk)
    talk.logger = logging.getLogger(__name__)
    cloned = object()
    agent = SimpleNamespace(
        name="agent",
        tool_manager=SimpleNamespace(clone=lambda: cloned),
        _pending_toolkit_specs=[],
        _tooling_revision="1",
    )
    session = Session()
    assert await talk._apply_user_toolkit_overrides(agent, session, None) is cloned


@pytest.mark.asyncio
async def test_mcp_restore_without_mongodb(no_mongo: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Redis MCP config reaches the tool manager restore hook."""
    config = UserMCPServerConfig(user_id="u1", agent_id="agent", server_name="demo", params={"url": "x"})
    await MCPPersistenceService().save_user_mcp_config(config)
    talk = AgentTalk.__new__(AgentTalk)
    talk.logger = logging.getLogger(__name__)
    manager = SimpleNamespace(add_mcp_server=AsyncMock(return_value=["tool"]))
    monkeypatch.setattr("parrot.handlers.agent._get_factory_map", lambda: {"demo": lambda **kw: kw})
    monkeypatch.setattr("parrot.security.vault_utils.get_vault_keyring", lambda: object())
    await talk._restore_user_mcp_servers(manager, SimpleNamespace(user_id="u1"), "agent")
    manager.add_mcp_server.assert_awaited_once_with({"url": "x"})
