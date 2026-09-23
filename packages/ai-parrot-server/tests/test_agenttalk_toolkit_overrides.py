"""Unit tests for AgentTalk's session-scoped toolkit overrides (FEAT-593)."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import parrot.handlers.agent as agent_module
from parrot.handlers.agent import AgentTalk
from parrot.handlers.toolkit_persistence import UserToolkitOverride
from parrot.tools.manager import ToolManager, get_toolkit_owner
from parrot.tools.spec import ToolkitSpec
from parrot.tools.toolkit import AbstractToolkit


class _Kit(AbstractToolkit):
    """Small configurable toolkit used to assert session replacement behavior."""

    def __init__(self, prefix: str = "", **kwargs):
        super().__init__(**kwargs)
        self.prefix = prefix

    async def echo(self, text: str) -> str:
        """Echo text with the configured prefix."""
        return self.prefix + text


class _Session(dict):
    """Mapping session that exposes the AgentTalk user identity attribute."""

    user_id = "7"


@pytest.fixture
def agent():
    """Build an agent-shaped object with one configured toolkit default."""
    tool_manager = ToolManager()
    tool_manager.register_toolkit(_Kit(prefix="agent"))
    return SimpleNamespace(
        name="a1",
        tool_manager=tool_manager,
        _tooling_revision="r1",
        _pending_toolkit_specs=[ToolkitSpec(slug="kit", params={"prefix": "agent"}, user_overridable=["prefix"])],
        _resolve_spec_class=lambda slug: _Kit,
    )


@pytest.fixture
def talk():
    """Create the handler without its HTTP view initialization."""
    handler = AgentTalk.__new__(AgentTalk)
    handler.logger = logging.getLogger("test.agenttalk.toolkit_overrides")
    return handler


def _service(overrides, revision="t1"):
    """Return a controllable configuration-service double."""
    return SimpleNamespace(
        load=AsyncMock(return_value=overrides),
        revision=AsyncMock(return_value=revision),
    )


def _kit_owner(tool_manager):
    """Return the owner of the test toolkit's only tool."""
    return get_toolkit_owner(tool_manager.get_tool("echo"))


@pytest.mark.asyncio
async def test_replace_not_duplicate(agent, talk, monkeypatch):
    """An override replaces the cloned toolkit instance without changing the agent's manager."""
    service = _service([UserToolkitOverride(user_id="7", agent_id="a1", slug="kit", params={"prefix": "user"})])
    monkeypatch.setattr(agent_module, "ToolkitConfigService", lambda: service)

    tool_manager = await talk._apply_user_toolkit_overrides(agent, _Session(), None)

    assert tool_manager is not agent.tool_manager
    assert tool_manager.list_tools() == ["echo"]
    assert _kit_owner(tool_manager).prefix == "user"
    assert _kit_owner(agent.tool_manager).prefix == "agent"


@pytest.mark.asyncio
async def test_stale_override_key_is_ignored(agent, talk, monkeypatch):
    """A saved override key revoked from user_overridable does not affect the toolkit."""
    service = _service([UserToolkitOverride(user_id="7", agent_id="a1", slug="kit", params={"unknown": "user"})])
    monkeypatch.setattr(agent_module, "ToolkitConfigService", lambda: service)

    tool_manager = await talk._apply_user_toolkit_overrides(agent, _Session(), None)

    assert _kit_owner(tool_manager).prefix == "agent"


@pytest.mark.asyncio
async def test_current_marker_short_circuits_rebuild(agent, talk, monkeypatch):
    """A session manager with a current marker is reused without construction work."""
    service = _service([UserToolkitOverride(user_id="7", agent_id="a1", slug="kit", params={"prefix": "user"})])
    monkeypatch.setattr(agent_module, "ToolkitConfigService", lambda: service)
    session = _Session()
    existing = agent.tool_manager.clone()
    session["a1_toolkit_overrides_rev"] = "r1:t1"

    tool_manager = await talk._apply_user_toolkit_overrides(agent, session, existing)

    assert tool_manager is existing
    assert _kit_owner(tool_manager).prefix == "agent"


@pytest.mark.asyncio
async def test_changed_revision_rebuilds_session_manager(agent, talk, monkeypatch):
    """A stale marker causes the existing session manager to be rebuilt in place."""
    service = _service([UserToolkitOverride(user_id="7", agent_id="a1", slug="kit", params={"prefix": "user"})])
    monkeypatch.setattr(agent_module, "ToolkitConfigService", lambda: service)
    session = _Session({"a1_toolkit_overrides_rev": "r1:old"})
    existing = agent.tool_manager.clone()

    tool_manager = await talk._apply_user_toolkit_overrides(agent, session, existing)

    assert tool_manager is existing
    assert _kit_owner(tool_manager).prefix == "user"
    assert session["a1_toolkit_overrides_rev"] == "r1:t1"


@pytest.mark.asyncio
async def test_no_overrides_returns_existing_manager_unchanged(agent, talk, monkeypatch):
    """No persisted overrides leaves the caller's session manager untouched."""
    service = _service([])
    monkeypatch.setattr(agent_module, "ToolkitConfigService", lambda: service)
    existing = agent.tool_manager.clone()

    tool_manager = await talk._apply_user_toolkit_overrides(agent, _Session(), existing)

    assert tool_manager is existing
    service.revision.assert_not_awaited()
