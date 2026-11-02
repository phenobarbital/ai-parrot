"""AgentTalk wiring for connection-backed OAuth toolkit hydration."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.agent import AgentTalk
from parrot.handlers.user_objects import UserObjectsHandler
from parrot.tools.manager import ToolManager
from parrot.tools.spec import agent_tooling_ref
from parrot.tools.toolkit import AbstractToolkit


class _Kit(AbstractToolkit):
    """Stub provider toolkit."""

    async def jira_ping(self) -> str:
        """Ping."""
        return "pong"


@pytest.fixture
def talk(monkeypatch):
    """AgentTalk with a real UserObjectsHandler and one active connection."""
    handler = AgentTalk.__new__(AgentTalk)
    handler.logger = logging.getLogger("test.agenttalk.hydration")
    handler._user_objects_handler = UserObjectsHandler()
    provider = MagicMock()
    provider.toolkit_factory.return_value = _Kit()
    registry = MagicMock()
    registry.get.return_value = provider
    rows = [SimpleNamespace(provider="jira", status="active")]
    monkeypatch.setattr("parrot.handlers.user_objects.list_users_integrations", AsyncMock(return_value=rows))
    monkeypatch.setattr("parrot.handlers.user_objects.OAuth2ProviderRegistry", lambda: registry)
    handler._provider = provider
    return handler


@pytest.fixture
def agent():
    return SimpleNamespace(name="a1")


@pytest.mark.asyncio
async def test_cold_session_hydrates(talk, agent):
    session: dict = {}
    tm = await talk._hydrate_cold_session(agent, session, "u1")
    assert isinstance(tm, ToolManager)
    assert session[f"{agent_tooling_ref(agent)}_tool_manager"] is tm
    assert tm.get_tool("jira_ping") is not None
    assert talk._provider.toolkit_factory.called


@pytest.mark.asyncio
async def test_existing_session_manager_not_overwritten(talk, agent):
    existing = ToolManager()
    session = {f"{agent_tooling_ref(agent)}_tool_manager": existing}
    assert await talk._hydrate_cold_session(agent, session, "u1") is None
    assert session[f"{agent_tooling_ref(agent)}_tool_manager"] is existing
    assert not talk._provider.toolkit_factory.called


@pytest.mark.asyncio
async def test_no_user_id_skips(talk, agent):
    assert await talk._hydrate_cold_session(agent, {}, None) is None


@pytest.mark.asyncio
async def test_configure_tool_manager_forwards_ids(talk, agent):
    session: dict = {}
    tm, _ = await talk._configure_tool_manager(
        {}, session, agent_name="a1", user_id="u1", agent_id="a1"
    )
    assert tm is not None
    assert talk._provider.toolkit_factory.called


@pytest.mark.asyncio
async def test_missing_ids_logs_warning(talk, caplog):
    with caplog.at_level(logging.WARNING):
        tm, _ = await talk.user_objects_handler.configure_tool_manager({}, {}, "a1")
    assert tm is None
    assert "Skipping OAuth toolkit hydration" in caplog.text
