"""Unit tests for TASK-3656: BotConfig.toolkits widening + factory normalization.

Verifies that:
1. ``BotConfig.toolkits`` accepts both bare-string slugs and full
   ``ToolkitSpec``-shaped dicts (Pydantic coerces the latter to
   ``ToolkitSpec``).
2. ``create_agent_factory``'s ``factory()`` normalizes the top-level
   ``config.toolkits`` / ``config.mcp_servers`` (and the legacy
   ``config.tools.toolkits`` / ``config.tools.mcp_servers``) through
   ``normalize_tooling`` and passes the result to the constructed bot as
   ``tools=`` / ``agent_mcp_servers=``.
3. ``create_agent_definition`` -> ``load_agent_definition_file`` round-trips
   a dict toolkit entry losslessly.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from parrot.registry import registry as registry_module
from parrot.registry.registry import AgentRegistry, BotConfig
from parrot.tools.spec import ToolkitSpec


def test_botconfig_accepts_specs():
    """A bare string and a spec-shaped dict both live in ``toolkits``."""
    cfg = BotConfig(
        name="a",
        class_name="BasicAgent",
        module="parrot.bots.agent",
        toolkits=["weather", {"slug": "jira", "params": {"default_project": "T"}}],
    )
    assert cfg.toolkits[0] == "weather"
    assert isinstance(cfg.toolkits[1], ToolkitSpec)
    assert cfg.toolkits[1].slug == "jira"
    assert cfg.toolkits[1].params == {"default_project": "T"}


@pytest.mark.asyncio
async def test_factory_passes_specs():
    """create_agent_factory's factory() normalizes toolkits/mcp_servers via normalize_tooling."""
    config = BotConfig(
        name="test_agent",
        class_name="Chatbot",
        module="parrot.bots.chatbot",
        toolkits=["weather", {"slug": "jira", "params": {"default_project": "T"}}],
        mcp_servers=[{"name": "srv1", "transport": "http", "url": "http://localhost:1234"}],
    )
    registry = AgentRegistry.__new__(AgentRegistry)

    _RegistryAbstractBot = registry_module.AbstractBot
    captured_kwargs = {}

    class _MockAgent(_RegistryAbstractBot):
        """Minimal concrete subclass of AbstractBot for testing."""

        def __init__(self, **kwargs):
            # Don't call super().__init__() — avoid real initialization
            captured_kwargs.update(kwargs)

        async def ask(self, *a, **kw):
            pass

        async def ask_stream(self, *a, **kw):
            pass

        async def conversation(self, *a, **kw):
            pass

        async def invoke(self, *a, **kw):
            pass

    with patch.object(registry_module, "importlib") as mock_importlib:
        mock_module = MagicMock()
        mock_module.Chatbot = _MockAgent
        mock_importlib.import_module.return_value = mock_module

        factory = registry.create_agent_factory(config)

    await factory(name="test_agent")

    tools = captured_kwargs["tools"]
    toolkit_specs = {t.slug: t for t in tools if isinstance(t, ToolkitSpec)}
    assert set(toolkit_specs) == {"weather", "jira"}
    assert toolkit_specs["jira"].params == {"default_project": "T"}

    mcp_specs = captured_kwargs["agent_mcp_servers"]
    assert len(mcp_specs) == 1
    assert mcp_specs[0].name == "srv1"


def test_create_agent_definition_roundtrip(tmp_path, monkeypatch):
    """A dict toolkit entry survives create_agent_definition -> load_agent_definition_file."""
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path)
    registry = AgentRegistry(agents_dir=tmp_path / "agents")

    config = BotConfig(
        name="roundtrip-agent",
        class_name="BasicAgent",
        module="parrot.bots.agent",
        toolkits=["weather", {"slug": "jira", "params": {"default_project": "T"}, "user_overridable": ["default_project"]}],
        mcp_servers=[{"name": "srv1", "transport": "http", "url": "http://localhost:1234"}],
    )

    path = registry.create_agent_definition(config, category="general")
    loaded = registry.load_agent_definition_file(path)
    assert loaded is True

    reloaded_config = registry._registered_agents["roundtrip-agent"].bot_config
    assert reloaded_config.toolkits[0] == "weather"
    assert isinstance(reloaded_config.toolkits[1], ToolkitSpec)
    assert reloaded_config.toolkits[1].slug == "jira"
    assert reloaded_config.toolkits[1].params == {"default_project": "T"}
    assert reloaded_config.toolkits[1].user_overridable == ["default_project"]
