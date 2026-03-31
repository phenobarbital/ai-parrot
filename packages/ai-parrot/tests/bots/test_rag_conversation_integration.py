"""Integration tests for RAG via the API path (TASK-502).

Verifies the full flow from bot creation (simulating YAML/DB-loaded config)
through configure() to _build_vector_context() with vector context appearing
in the result — without any external service dependency.

WORKTREE NOTE:
  Uses the same importlib strategy as test_vector_context_integration.py to
  load the worktree's abstract.py so that FEAT-072 fixes are exercised.
"""
from __future__ import annotations

import sys
import types as _types_mod
import importlib.util
from pathlib import Path
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# Load the *worktree* version of abstract.py (same as TASK-500 test)
# ---------------------------------------------------------------------------
_WORKTREE_ABSTRACT = (
    Path(__file__).resolve().parents[2]
    / "src" / "parrot" / "bots" / "abstract.py"
)

for _clear_key in [
    "parrot.bots.abstract",
    "parrot.models.responses",
    "parrot.clients",
    "parrot.clients.base",
]:
    sys.modules.pop(_clear_key, None)

# Pre-create parrot.bots stub (avoids agent→notifications→navconfig chain)
if not hasattr(sys.modules.get("parrot.bots"), "AbstractBot"):
    _bots_stub = _types_mod.ModuleType("parrot.bots")
    _bots_stub.__path__ = [
        str(_WORKTREE_ABSTRACT.parent),
        "/home/jesuslara/proyectos/navigator/ai-parrot/packages/ai-parrot/src/parrot/bots",
    ]
    _bots_stub.__package__ = "parrot.bots"
    sys.modules["parrot.bots"] = _bots_stub

_spec = importlib.util.spec_from_file_location("parrot.bots.abstract", str(_WORKTREE_ABSTRACT))
_abstract_module = importlib.util.module_from_spec(_spec)
_abstract_module.__package__ = "parrot.bots"
sys.modules["parrot.bots.abstract"] = _abstract_module
_spec.loader.exec_module(_abstract_module)

AbstractBot = _abstract_module.AbstractBot


# ---------------------------------------------------------------------------
# Helper: build a minimal mock bot for integration tests
# ---------------------------------------------------------------------------

def _make_bot(
    vector_store_config: dict = None,
    use_vectorstore: bool = False,
) -> MagicMock:
    """Return a MagicMock bot suitable for integration tests.

    Args:
        vector_store_config: Dict to use as vector store configuration.
        use_vectorstore: Initial value for _use_vector.

    Returns:
        A MagicMock with all attributes required by configure() and
        _build_vector_context().
    """
    bot = MagicMock()
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
    bot.tool_manager = None
    bot._llm_raw = None
    bot._llm_model = None
    bot._llm_preset = None
    bot._llm_kwargs = {}
    bot._llm_config = None
    bot._llm = None

    # Sync methods
    bot.configure_conversation_memory = MagicMock()
    bot.define_store_config = MagicMock(return_value=None)
    bot._apply_store_config = MagicMock()
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

    # Async methods
    bot.configure_kb = AsyncMock()
    bot.configure_local_kb = AsyncMock()
    bot._configure_prompt_builder = AsyncMock()
    bot.warmup_embeddings = AsyncMock()
    bot._ensure_collection = AsyncMock()
    bot._configure_kb_selector = AsyncMock()
    bot.get_vector_context = AsyncMock(return_value=("", {}))

    return bot


# ---------------------------------------------------------------------------
# Integration test: full flow vector_store_config → configure → context
# ---------------------------------------------------------------------------

class TestRAGConversationIntegration:
    """Verify the full RAG flow from bot config through configure to context."""

    @pytest.mark.asyncio
    async def test_configure_with_vector_store_config_enables_store(self):
        """Bot created with vector_store_config (no use_vectorstore) must have store after configure().

        This simulates a bot loaded from YAML or the database where the registry
        passes vector_store_config but does not explicitly set use_vectorstore=True.
        FEAT-072 Bug: configure() used to skip configure_store() in this case.
        """
        vector_config = {
            'vector_store': 'postgres',
            'table': 'test_embeddings',
            'dimension': 768,
        }
        bot = _make_bot(vector_store_config=vector_config)

        # configure_store is the method that sets bot.store — mock it to inject
        # a real mock store so we can verify downstream behavior.
        mock_store = MagicMock()
        mock_store.__aenter__ = AsyncMock(return_value=mock_store)
        mock_store.__aexit__ = AsyncMock(return_value=False)

        def _configure_store_side_effect():
            bot.store = mock_store

        bot.configure_store.side_effect = _configure_store_side_effect

        # Initial state: _use_vector is False, store is None
        assert bot._use_vector is False
        assert bot.store is None

        await AbstractBot.configure(bot)

        # After configure: auto-enable should have fired
        assert bot._use_vector is True
        # configure_store() was called
        bot.configure_store.assert_called_once()
        # store was set by configure_store
        assert bot.store is mock_store

    @pytest.mark.asyncio
    async def test_vector_context_returned_when_store_configured(self):
        """After configure() enables the store, _build_vector_context should return content.

        Simulates the full RAG retrieval path:
          configure(vector_store_config) → store set → _build_vector_context() → returns docs
        """
        vector_config = {'vector_store': 'postgres', 'table': 'test_embeddings'}
        bot = _make_bot(vector_store_config=vector_config)

        # Inject a mock store via configure_store
        mock_store = MagicMock()
        doc_context = "Compensation is based on performance and tenure."
        bot.get_vector_context = AsyncMock(return_value=(doc_context, {"source": "hr_docs"}))

        def _inject_store():
            bot.store = mock_store

        bot.configure_store.side_effect = _inject_store

        # Configure (auto-enable + store injection)
        await AbstractBot.configure(bot)

        # Now call _build_vector_context
        context, metadata = await AbstractBot._build_vector_context(
            bot, "How does compensation work?"
        )

        # Vector context must have been returned
        assert context == doc_context
        assert metadata == {"source": "hr_docs"}
        bot.get_vector_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_vector_context_without_store_config(self):
        """Bot without any vector config should skip RAG and return empty context."""
        bot = _make_bot()  # no vector_store_config
        assert bot._vector_store is None

        await AbstractBot.configure(bot)

        # Store should NOT be configured
        assert bot._use_vector is False
        bot.configure_store.assert_not_called()

        # _build_vector_context should return empty
        context, metadata = await AbstractBot._build_vector_context(bot, "test query")
        assert context == ""
        assert metadata == {}

    @pytest.mark.asyncio
    async def test_debug_log_when_rag_skipped(self):
        """A DEBUG log must be emitted when RAG is skipped (store is None)."""
        bot = _make_bot()  # no vector_store_config
        await AbstractBot.configure(bot)

        # Reset debug call count (configure may have emitted debug logs)
        bot.logger.debug.reset_mock()

        await AbstractBot._build_vector_context(bot, "test query")

        # Verify at least one debug message was logged about skipping
        bot.logger.debug.assert_called()
        # The message should mention the store
        any_skip_msg = any(
            "store" in str(call).lower()
            for call in bot.logger.debug.call_args_list
        )
        assert any_skip_msg, "Expected debug log mentioning store was missing"

    @pytest.mark.asyncio
    async def test_vector_context_not_retrieved_when_use_vectors_false(self):
        """When use_vectors=False is explicitly passed, RAG must be skipped."""
        bot = _make_bot(vector_store_config={'vector_store': 'postgres', 'table': 'docs'})
        mock_store = MagicMock()

        def _inject_store():
            bot.store = mock_store

        bot.configure_store.side_effect = _inject_store
        await AbstractBot.configure(bot)

        # Store is set, but caller opts out of vector context
        assert bot.store is mock_store

        context, metadata = await AbstractBot._build_vector_context(
            bot, "test query", use_vectors=False
        )

        assert context == ""
        assert metadata == {}
        bot.get_vector_context.assert_not_called()
