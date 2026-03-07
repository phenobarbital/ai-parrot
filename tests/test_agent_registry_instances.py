"""Tests for AgentRegistry instance management."""
import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.registry.registry import AgentRegistry, BotMetadata
from parrot.bots.abstract import AbstractBot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _FakeAgent(AbstractBot):
    """Minimal concrete AbstractBot for testing."""

    def __init__(self, name: str = "fake", **kwargs):
        self._name = name

    @property
    def name(self):
        return self._name

    async def ask(self, prompt: str, **kwargs):
        return f"echo: {prompt}"

    async def configure(self, *args, **kwargs):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def registry(tmp_path):
    """Fresh AgentRegistry pointing at a temp directory."""
    return AgentRegistry(agents_dir=tmp_path)


@pytest.fixture()
def agent():
    return _FakeAgent(name="TestBot")


# ---------------------------------------------------------------------------
# register_instance
# ---------------------------------------------------------------------------
class TestRegisterInstance:
    """Tests for AgentRegistry.register_instance()."""

    def test_register_stores_metadata(self, registry, agent):
        registry.register_instance("TestBot", agent, replace=True)
        assert registry.has("TestBot")

    def test_register_metadata_is_singleton(self, registry, agent):
        registry.register_instance("TestBot", agent)
        meta = registry.get_metadata("TestBot")
        assert meta is not None
        assert meta.singleton is True

    def test_register_instance_cached(self, registry, agent):
        registry.register_instance("TestBot", agent)
        meta = registry.get_metadata("TestBot")
        assert meta._instance is agent

    def test_get_bot_instance_returns_agent(self, registry, agent):
        registry.register_instance("TestBot", agent)
        result = registry.get_bot_instance("TestBot")
        assert result is agent
        assert isinstance(result, AbstractBot)

    def test_get_bot_instance_unknown_returns_none(self, registry):
        assert registry.get_bot_instance("NoSuchBot") is None

    @pytest.mark.asyncio
    async def test_get_instance_returns_agent(self, registry, agent):
        registry.register_instance("TestBot", agent)
        result = await registry.get_instance("TestBot")
        assert result is agent

    def test_duplicate_without_replace_warns(self, registry, agent):
        registry.register_instance("TestBot", agent)
        # Second call without replace should warn but not overwrite
        agent2 = _FakeAgent(name="TestBot2")
        registry.register_instance("TestBot", agent2)
        # Original still in place
        assert registry.get_bot_instance("TestBot") is agent

    def test_duplicate_with_replace(self, registry, agent):
        registry.register_instance("TestBot", agent)
        agent2 = _FakeAgent(name="TestBot2")
        registry.register_instance("TestBot", agent2, replace=True)
        assert registry.get_bot_instance("TestBot") is agent2

    def test_non_abstractbot_raises(self, registry):
        with pytest.raises(TypeError, match="must be an AbstractBot"):
            registry.register_instance("Bad", object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_bot_instance after class-based register
# ---------------------------------------------------------------------------
class TestGetBotInstanceClassBased:
    """get_bot_instance returns None when no instance has been created yet."""

    def test_returns_none_before_instantiation(self, registry):
        registry.register("ClassBot", _FakeAgent, singleton=True)
        # No instance created yet
        assert registry.get_bot_instance("ClassBot") is None

    @pytest.mark.asyncio
    async def test_returns_instance_after_get_instance(self, registry):
        registry.register("ClassBot", _FakeAgent, singleton=True)
        instance = await registry.get_instance("ClassBot")
        assert instance is not None
        # Now get_bot_instance should return the same thing
        assert registry.get_bot_instance("ClassBot") is instance
