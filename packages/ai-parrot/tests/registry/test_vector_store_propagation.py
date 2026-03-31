"""Unit tests for YAML agent definition vector store key mismatch fix (TASK-501).

Tests that:
1. AgentRegistry.create_agent_factory() sets use_vectorstore=True when vector_store is present
2. BotMetadata.get_instance() handles both 'vector_store' and 'vector_store_config' keys

WORKTREE NOTE:
  Like test_vector_context_integration.py, this file loads the worktree version
  of registry.py directly so that the FEAT-072 fix is tested rather than the
  currently-installed (pre-fix) package version.
"""
from __future__ import annotations

import sys
import types as _types_mod
import importlib.util
from pathlib import Path
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# Load the *worktree* version of registry.py
# ---------------------------------------------------------------------------
_WORKTREE_REGISTRY = (
    Path(__file__).resolve().parents[2]  # packages/ai-parrot
    / "src" / "parrot" / "registry" / "registry.py"
)

# Clear the module so we can replace with the worktree version.
# Also clear parrot.models.responses stub which is missing InvokeResult.
for _clear_key in [
    "parrot.registry.registry",
    "parrot.registry",
    "parrot.models.responses",
    "parrot.clients",
    "parrot.clients.base",
    "parrot.bots.abstract",
]:
    sys.modules.pop(_clear_key, None)

# Pre-create a minimal parrot.registry package stub (avoids __init__ side-effects).
_registry_pkg = sys.modules.get("parrot.registry")
if _registry_pkg is None or not hasattr(_registry_pkg, "AgentRegistry"):
    _reg_stub = _types_mod.ModuleType("parrot.registry")
    _reg_stub.__path__ = [str(_WORKTREE_REGISTRY.parent)]
    _reg_stub.__package__ = "parrot.registry"
    sys.modules["parrot.registry"] = _reg_stub

# Also ensure parrot.bots is stubbed to avoid the agent→notifications chain
_bots_pkg = sys.modules.get("parrot.bots")
if _bots_pkg is None:
    _bots_stub = _types_mod.ModuleType("parrot.bots")
    _bots_stub.__path__ = [
        str(_WORKTREE_REGISTRY.parents[1] / "bots"),
        "/home/jesuslara/proyectos/navigator/ai-parrot/packages/ai-parrot/src/parrot/bots",
    ]
    _bots_stub.__package__ = "parrot.bots"
    sys.modules["parrot.bots"] = _bots_stub

# Load the worktree registry.py as parrot.registry.registry
_spec = importlib.util.spec_from_file_location(
    "parrot.registry.registry", str(_WORKTREE_REGISTRY)
)
_registry_module = importlib.util.module_from_spec(_spec)
_registry_module.__package__ = "parrot.registry"
sys.modules["parrot.registry.registry"] = _registry_module
_spec.loader.exec_module(_registry_module)

AgentRegistry = _registry_module.AgentRegistry
BotMetadata = _registry_module.BotMetadata
BotConfig = _registry_module.BotConfig
StoreConfig = _registry_module.StoreConfig


# ---------------------------------------------------------------------------
# Tests: create_agent_factory() vector store propagation
# ---------------------------------------------------------------------------

class TestCreateAgentFactoryVectorStore:
    """Test that create_agent_factory propagates use_vectorstore when vector_store is set."""

    def _make_bot_config_with_vector_store(self) -> BotConfig:
        """Return a minimal BotConfig with a vector_store section."""
        return BotConfig(
            name="test_agent",
            class_name="Chatbot",
            module="parrot.bots.chatbot",
            vector_store=StoreConfig(
                vector_store="postgres",
                table="test_embeddings",
                dimension=768,
            ),
        )

    def _make_bot_config_without_vector_store(self) -> BotConfig:
        """Return a minimal BotConfig WITHOUT a vector_store section."""
        return BotConfig(
            name="test_agent",
            class_name="Chatbot",
            module="parrot.bots.chatbot",
        )

    def test_vector_store_sets_use_vectorstore(self):
        """When vector_store is in BotConfig, factory kwargs must include use_vectorstore=True."""
        config = self._make_bot_config_with_vector_store()
        registry = AgentRegistry.__new__(AgentRegistry)

        # Capture what merged_args would contain by intercepting the agent_class call.
        # The factory checks isinstance(instance, AbstractBot), so we subclass the
        # AbstractBot that the registry module has imported.
        _RegistryAbstractBot = _registry_module.AbstractBot
        captured_kwargs = {}

        class _MockAgent(_RegistryAbstractBot):
            """Minimal concrete subclass of AbstractBot for testing."""
            def __init__(self, **kwargs):
                # Don't call super().__init__() — avoid real initialization
                captured_kwargs.update(kwargs)

            async def ask(self, *a, **kw): pass
            async def ask_stream(self, *a, **kw): pass
            async def conversation(self, *a, **kw): pass
            async def invoke(self, *a, **kw): pass

        with patch.object(
            _registry_module, "importlib"
        ) as mock_importlib:
            mock_module = MagicMock()
            mock_module.Chatbot = _MockAgent
            mock_importlib.import_module.return_value = mock_module

            factory = registry.create_agent_factory(config)

        # Call the factory (it returns a coroutine since factory is async)
        import asyncio

        async def _run():
            return await factory(name="test_agent", from_database=False)

        asyncio.get_event_loop().run_until_complete(_run())

        # Verify use_vectorstore=True was passed to the constructor
        assert captured_kwargs.get("use_vectorstore") is True, (
            "create_agent_factory must pass use_vectorstore=True when BotConfig has vector_store"
        )
        assert "vector_store_config" in captured_kwargs, (
            "create_agent_factory must pass vector_store_config when BotConfig has vector_store"
        )

    def test_no_vector_store_no_flag(self):
        """When BotConfig has no vector_store, use_vectorstore must NOT be set to True."""
        config = self._make_bot_config_without_vector_store()
        registry = AgentRegistry.__new__(AgentRegistry)

        _RegistryAbstractBot = _registry_module.AbstractBot
        captured_kwargs = {}

        class _MockAgent(_RegistryAbstractBot):
            """Minimal concrete subclass of AbstractBot for testing."""
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)

            async def ask(self, *a, **kw): pass
            async def ask_stream(self, *a, **kw): pass
            async def conversation(self, *a, **kw): pass
            async def invoke(self, *a, **kw): pass

        with patch.object(_registry_module, "importlib") as mock_importlib:
            mock_module = MagicMock()
            mock_module.Chatbot = _MockAgent
            mock_importlib.import_module.return_value = mock_module

            factory = registry.create_agent_factory(config)

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            factory(name="test_agent", from_database=False)
        )

        assert captured_kwargs.get("use_vectorstore") is not True, (
            "use_vectorstore must not be True when no vector_store config is present"
        )
        assert "vector_store_config" not in captured_kwargs, (
            "vector_store_config must not be present when no vector_store config is set"
        )


# ---------------------------------------------------------------------------
# Tests: BotMetadata.get_instance() handles both key names
# ---------------------------------------------------------------------------

class TestBotMetadataVectorStoreKeys:
    """Test that BotMetadata.get_instance() handles both vector_store and vector_store_config."""

    def _make_mock_metadata(self, startup_config: dict) -> BotMetadata:
        """Return a minimal BotMetadata with the given startup_config."""
        _RegistryAbstractBot = _registry_module.AbstractBot

        class _DummyBot(_RegistryAbstractBot):
            """Minimal concrete AbstractBot subclass for BotMetadata testing."""
            def __init__(self, name="test", **kwargs):
                # Don't call real super().__init__() to avoid DB connections
                self.name = name
                self._use_vector = kwargs.get("use_vectorstore", False)
                self._vector_store = kwargs.get("vector_store_config") or kwargs.get("vector_store")
                self.store = None

            def _apply_store_config(self, config):
                pass

            async def ask(self, *a, **kw): pass
            async def ask_stream(self, *a, **kw): pass
            async def conversation(self, *a, **kw): pass
            async def invoke(self, *a, **kw): pass

        return BotMetadata(
            name="test_bot",
            factory=_DummyBot,
            module_path="test",
            file_path=Path("/tmp/test.py"),
            singleton=False,
            # at_startup=True avoids get_instance() calling instance.configure()
            # which would require a fully initialized bot (DB, LLM, etc.)
            at_startup=True,
            startup_config=startup_config,
        )

    @pytest.mark.asyncio
    async def test_instantiate_with_vector_store_key(self):
        """Should find config under 'vector_store' key and apply it."""
        store_dict = {"vector_store": "postgres", "table": "test_table", "dimension": 768}
        metadata = self._make_mock_metadata(
            startup_config={"vector_store": store_dict}
        )

        instance = await metadata.get_instance(from_database=False)

        # The 'vector_store' key should have been popped and the config applied
        assert instance._use_vector is True, (
            "get_instance must set _use_vector=True when 'vector_store' key is in startup_config"
        )

    @pytest.mark.asyncio
    async def test_instantiate_with_vector_store_config_key(self):
        """Should find config under 'vector_store_config' key and apply it."""
        store_dict = {"vector_store": "postgres", "table": "test_table", "dimension": 768}
        metadata = self._make_mock_metadata(
            startup_config={"vector_store_config": store_dict}
        )

        instance = await metadata.get_instance(from_database=False)

        # The 'vector_store_config' key should have been popped and the config applied
        assert instance._use_vector is True, (
            "get_instance must set _use_vector=True when 'vector_store_config' key is in startup_config"
        )

    @pytest.mark.asyncio
    async def test_no_vector_store_key_no_use_vector(self):
        """Bot without any vector store config should have _use_vector=False."""
        metadata = self._make_mock_metadata(startup_config={})

        instance = await metadata.get_instance(from_database=False)

        assert instance._use_vector is False, (
            "_use_vector must remain False when no vector store config is present"
        )
