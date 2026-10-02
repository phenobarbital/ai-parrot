"""End-to-end test for per-tool/toolkit kwargs declared in YAML BotConfig.

Exercises the full, previously-broken pipeline: AgentRegistry.create_agent_factory()
merges ToolConfig.tools/toolkits (now name -> kwargs mappings) into the bot's
`tools=` list, AbstractBot._initialize_tools() resolves each {name: kwargs}
entry, and ToolManager.register_toolkit()/load_tool() forward kwargs to the
real constructor. Before this change, the toolkit half of this pipeline was a
dead `pass` stub, so no toolkit declared in YAML was ever actually
instantiated — this test is the first to exercise that real wiring.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

import parrot.registry.registry as registry_module
from parrot.registry.registry import AgentRegistry, BotConfig
from parrot.models.basic import ToolConfig
from parrot.bots.abstract import AbstractBot
from parrot.tools.manager import ToolManager
from parrot.tools.registry import ToolkitRegistry
from parrot.tools.toolkit import AbstractToolkit


class KwargsCaptureToolkit(AbstractToolkit):
    """Toolkit that records the kwargs it was constructed with."""

    last_kwargs: dict = {}

    def __init__(self, some_kwarg=None, **kwargs):
        super().__init__(**kwargs)
        type(self).last_kwargs = {"some_kwarg": some_kwarg}


@pytest.fixture
def toolkit_registry_sandbox():
    """Snapshot and restore ToolkitRegistry's lazily-built class registry
    so this test's registration doesn't leak into other tests."""
    original = ToolkitRegistry.get_registry()
    snapshot = dict(original)
    try:
        yield
    finally:
        ToolkitRegistry._registry = snapshot
        KwargsCaptureToolkit.last_kwargs = {}


class _MockAgent(AbstractBot):
    """Minimal AbstractBot subclass: wires up just enough state to exercise
    the real _initialize_tools() pipeline without DB/LLM initialization
    (mirrors the pattern in test_vector_store_propagation.py)."""

    def __init__(self, **kwargs):
        self.logger = logging.getLogger("MockAgent.Bot")
        self.tool_manager = ToolManager(logger=self.logger)
        self._pageindex_toolkit = None
        self._graphindex_toolkit = None
        self._llmwiki_toolkit = None
        tools = kwargs.get("tools") or []
        if tools:
            self._initialize_tools(tools)

    async def ask(self, *a, **kw):
        pass

    async def ask_stream(self, *a, **kw):
        pass

    async def conversation(self, *a, **kw):
        pass

    async def invoke(self, *a, **kw):
        pass


@pytest.mark.asyncio
async def test_toolkit_kwargs_flow_from_config_to_constructor(toolkit_registry_sandbox):
    """BotConfig.tools.toolkits kwargs reach the toolkit's __init__ through
    create_agent_factory() -> AbstractBot(tools=...) -> _initialize_tools()
    -> ToolManager.register_toolkit(name, **kwargs)."""
    ToolkitRegistry.register("kwargscapturetoolkit", KwargsCaptureToolkit)

    config = BotConfig(
        name="kwargs-e2e-agent",
        class_name="MockAgent",
        module="tests.registry._fake_module_for_kwargs_test",
        tools=ToolConfig(toolkits={"KwargsCaptureToolkit": {"some_kwarg": "hello"}}),
    )

    registry = AgentRegistry.__new__(AgentRegistry)

    with patch.object(registry_module, "importlib") as mock_importlib:
        mock_module = MagicMock()
        mock_module.MockAgent = _MockAgent
        mock_importlib.import_module.return_value = mock_module

        factory = registry.create_agent_factory(config)
        bot = await factory()

    assert KwargsCaptureToolkit.last_kwargs == {"some_kwarg": "hello"}
    assert isinstance(bot, _MockAgent)


@pytest.mark.asyncio
async def test_legacy_string_toolkit_still_resolves(toolkit_registry_sandbox):
    """Legacy YAML shape (bare toolkit name, no kwargs) still resolves and
    registers through the same merged pipeline."""
    ToolkitRegistry.register("kwargscapturetoolkit", KwargsCaptureToolkit)

    config = BotConfig(
        name="legacy-e2e-agent",
        class_name="MockAgent",
        module="tests.registry._fake_module_for_kwargs_test",
        tools=ToolConfig(toolkits=["KwargsCaptureToolkit"]),
    )

    registry = AgentRegistry.__new__(AgentRegistry)

    with patch.object(registry_module, "importlib") as mock_importlib:
        mock_module = MagicMock()
        mock_module.MockAgent = _MockAgent
        mock_importlib.import_module.return_value = mock_module

        factory = registry.create_agent_factory(config)
        await factory()

    assert KwargsCaptureToolkit.last_kwargs == {"some_kwarg": None}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
