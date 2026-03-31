"""Unit tests for AbstractBot vector store auto-enable and diagnostic logging (TASK-500).

Tests that:
1. configure() auto-enables vector store when vector_store_config is present
2. _build_vector_context() logs the reason when RAG is skipped

WORKTREE NOTE:
  This test file loads the *worktree* version of abstract.py directly via
  importlib so that changes committed here are tested even when the shared
  .venv still points to the main-repo source.  The technique pre-registers a
  minimal ``parrot.bots`` package stub in sys.modules to satisfy the relative
  imports inside abstract.py without triggering the full bot package chain
  (which would fail due to stubs for navconfig / notify installed by the
  shared conftest).
"""
from __future__ import annotations

import sys
import types as _types_mod
import importlib.util
from pathlib import Path
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# Load the *worktree* version of abstract.py
# ---------------------------------------------------------------------------
_WORKTREE_ABSTRACT = (
    Path(__file__).resolve().parents[2]  # packages/ai-parrot
    / "src" / "parrot" / "bots" / "abstract.py"
)

# Remove any previously-cached version of parrot.bots.abstract so we can
# replace it with the worktree copy.
sys.modules.pop("parrot.bots.abstract", None)

# Pre-create a minimal parrot.bots package stub.  This prevents abstract.py's
# relative ``from .prompts import ...`` from triggering the real __init__.py
# (which in turn would try to import agent.py → notifications → navconfig.DEBUG
# which is missing from the conftest stub).
_bots_pkg = sys.modules.get("parrot.bots")
if _bots_pkg is None or not hasattr(_bots_pkg, "AbstractBot"):
    _bots_stub = _types_mod.ModuleType("parrot.bots")
    _bots_stub.__path__ = [
        str(_WORKTREE_ABSTRACT.parent),
        # Also expose main-repo path so compiled extensions are reachable
        str(
            Path(sys.modules.get("parrot.bots.abstract", _types_mod.ModuleType("x")).__dict__.get(
                "__file__",
                "/home/jesuslara/proyectos/navigator/ai-parrot/packages/ai-parrot/src/parrot/bots/abstract.py",
            )).parent
            if False  # skip the conditional computation
            else "/home/jesuslara/proyectos/navigator/ai-parrot/packages/ai-parrot/src/parrot/bots"
        ),
    ]
    _bots_stub.__package__ = "parrot.bots"
    sys.modules["parrot.bots"] = _bots_stub

# Load the worktree abstract.py as parrot.bots.abstract
_spec = importlib.util.spec_from_file_location("parrot.bots.abstract", str(_WORKTREE_ABSTRACT))
_abstract_module = importlib.util.module_from_spec(_spec)
_abstract_module.__package__ = "parrot.bots"
sys.modules["parrot.bots.abstract"] = _abstract_module
_spec.loader.exec_module(_abstract_module)

AbstractBot = _abstract_module.AbstractBot


# ---------------------------------------------------------------------------
# Helper: build a minimal mock bot compatible with configure() / _build_vector_context()
# ---------------------------------------------------------------------------

def _make_mock_bot(
    use_vectorstore: bool = False,
    vector_store_config: dict = None,
) -> MagicMock:
    """Return a MagicMock that satisfies AbstractBot.configure() and _build_vector_context().

    Args:
        use_vectorstore: Initial value for _use_vector.
        vector_store_config: Initial value for _vector_store.

    Returns:
        A MagicMock with the required attributes and async stubs.
    """
    bot = MagicMock(spec_set=False)
    # Core flags used by configure() / _build_vector_context()
    bot._configured = False
    bot._use_vector = use_vectorstore
    bot._vector_store = vector_store_config
    bot.store = None
    bot.app = None
    bot.logger = MagicMock()
    bot._prompt_builder = None
    bot._use_local_kb = False
    bot.warmup_on_configure = False
    bot.use_kb = False
    bot.use_kb_selector = False
    # Sync stubs
    bot.configure_conversation_memory = MagicMock()
    bot.define_store_config = MagicMock(return_value=None)
    bot._apply_store_config = MagicMock()
    bot.configure_store = MagicMock()
    bot._define_prompt = MagicMock()
    bot.get_tools_summary = MagicMock(return_value={
        "tools_enabled": False,
        "operation_mode": "chat",
        "tools_count": 0,
        "categories": [],
        "effective_mode": "chat",
    })
    bot._resolve_llm_config = MagicMock(return_value=MagicMock())
    bot._create_llm_client = MagicMock(return_value=MagicMock())
    bot.sync_tools = MagicMock()
    bot.tool_manager = None
    bot._llm_raw = None
    bot._llm_model = None
    bot._llm_preset = None
    bot._llm_kwargs = {}
    bot._llm_config = None
    bot._llm = None
    # Async stubs
    bot.configure_kb = AsyncMock()
    bot.configure_local_kb = AsyncMock()
    bot._configure_prompt_builder = AsyncMock()
    bot.warmup_embeddings = AsyncMock()
    bot._ensure_collection = AsyncMock()
    bot._configure_kb_selector = AsyncMock()
    bot.get_vector_context = AsyncMock(return_value=("", {}))
    return bot


# ---------------------------------------------------------------------------
# Tests: configure() auto-enable
# ---------------------------------------------------------------------------

class TestConfigureAutoEnablesVectorStore:
    """Test that configure() auto-enables vector store when config is present."""

    @pytest.mark.asyncio
    async def test_auto_enable_with_vector_store_config(self):
        """Bot with vector_store_config but no use_vectorstore should auto-enable."""
        bot = _make_mock_bot(
            use_vectorstore=False,
            vector_store_config={'name': 'postgres', 'table': 'test_table'},
        )
        assert bot._use_vector is False
        assert bot._vector_store is not None

        await AbstractBot.configure(bot)

        assert bot._use_vector is True
        bot.configure_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_auto_enable_without_config(self):
        """Bot without vector config should NOT auto-enable."""
        bot = _make_mock_bot(use_vectorstore=False, vector_store_config=None)

        await AbstractBot.configure(bot)

        assert bot._use_vector is False
        assert bot.store is None
        bot.configure_store.assert_not_called()

    @pytest.mark.asyncio
    async def test_explicit_use_vector_true_still_works(self):
        """Bot with explicit use_vectorstore=True should still configure store."""
        bot = _make_mock_bot(
            use_vectorstore=True,
            vector_store_config={'name': 'postgres', 'table': 'test_table'},
        )
        assert bot._use_vector is True

        await AbstractBot.configure(bot)

        assert bot._use_vector is True
        bot.configure_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_enable_runs_after_define_store_config(self):
        """Auto-enable check fires AFTER define_store_config() / _apply_store_config()."""
        bot = _make_mock_bot(use_vectorstore=False, vector_store_config=None)

        # Simulate define_store_config returning a config, and _apply_store_config
        # setting _vector_store as a side effect.
        dummy_config = MagicMock()
        dummy_config.auto_create = False
        bot.define_store_config = MagicMock(return_value=dummy_config)

        def _apply_side_effect(cfg):
            bot._vector_store = {'name': 'postgres', 'table': 'my_table'}

        bot._apply_store_config.side_effect = _apply_side_effect

        await AbstractBot.configure(bot)

        # _vector_store was set by _apply_store_config → auto-enable should fire
        assert bot._use_vector is True
        bot.configure_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_dict_does_not_auto_enable(self):
        """An empty dict for _vector_store should NOT trigger auto-enable."""
        bot = _make_mock_bot(use_vectorstore=False, vector_store_config={})

        await AbstractBot.configure(bot)

        # empty dict is falsy → guard `if not self._use_vector and self._vector_store`
        # should NOT fire
        assert bot._use_vector is False
        bot.configure_store.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: _build_vector_context diagnostic logging
# ---------------------------------------------------------------------------

class TestBuildVectorContextLogging:
    """Test diagnostic logging when vector context is skipped."""

    @pytest.mark.asyncio
    async def test_logs_when_store_is_none(self):
        """Should log debug message when store is None."""
        bot = _make_mock_bot()
        bot.store = None

        result = await AbstractBot._build_vector_context(bot, "test query")

        assert result == ("", {})
        bot.logger.debug.assert_called()
        call_args = bot.logger.debug.call_args[0][0]
        assert "store" in call_args.lower()

    @pytest.mark.asyncio
    async def test_logs_when_use_vectors_false(self):
        """Should log debug message when use_vectors=False."""
        bot = _make_mock_bot()
        # Give bot a non-None store so the "store is None" branch doesn't fire
        bot.store = MagicMock()

        result = await AbstractBot._build_vector_context(bot, "test query", use_vectors=False)

        assert result == ("", {})
        bot.logger.debug.assert_called()
        call_args = bot.logger.debug.call_args[0][0]
        assert "use_vectors" in call_args.lower() or "false" in call_args.lower()

    @pytest.mark.asyncio
    async def test_no_skip_log_when_store_and_use_vectors_true(self):
        """Should NOT log skip message when store is present and use_vectors=True."""
        bot = _make_mock_bot()
        bot.store = MagicMock()
        bot.get_vector_context = AsyncMock(return_value=("doc context", {"source": "doc1"}))

        result = await AbstractBot._build_vector_context(bot, "test query", use_vectors=True)

        # Result is the mocked value, NOT ("", {})
        assert result == ("doc context", {"source": "doc1"})
        # No skip debug message should have been emitted
        for call in bot.logger.debug.call_args_list:
            if call[0]:
                assert "skipped" not in call[0][0].lower()
