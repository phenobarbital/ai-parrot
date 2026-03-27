"""Tests for AbstractBot warmup registry integration (TASK-378)."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset EmbeddingRegistry singleton between tests."""
    from parrot.embeddings.registry import EmbeddingRegistry

    EmbeddingRegistry._instance = None
    yield
    if EmbeddingRegistry._instance is not None:
        EmbeddingRegistry._instance.clear()
        EmbeddingRegistry._instance = None


def _make_minimal_bot():
    """Return a MagicMock that exposes the attributes AbstractBot.warmup_embeddings reads."""
    bot = MagicMock()
    bot.kb_store = None
    bot.knowledge_bases = []
    bot.store = None
    bot.embedding_model = {
        "model_name": "all-MiniLM-L6-v2",
        "model_type": "huggingface",
    }
    # Attach the real warmup_embeddings method (unbound)
    from parrot.bots.abstract import AbstractBot
    bot.warmup_embeddings = AbstractBot.warmup_embeddings.__get__(bot, type(bot))
    bot.logger = MagicMock()
    return bot


class TestBotWarmupRegistryIntegration:
    @pytest.mark.asyncio
    async def test_warmup_calls_registry_preload(self):
        """warmup_embeddings() delegates embedding loading to registry.preload()."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        bot = _make_minimal_bot()
        # Bot has an embedding model configured
        bot.embedding_model = {
            "model_name": "all-MiniLM-L6-v2",
            "model_type": "huggingface",
        }
        # No kb_store, no store for this minimal test
        bot.kb_store = None
        bot.store = None

        with patch.object(registry, "preload", new_callable=AsyncMock) as mock_preload:
            await bot.warmup_embeddings()

        # preload should not be called if there are no models to load
        # (no kb_store, no store)
        mock_preload.assert_not_called()

    @pytest.mark.asyncio
    async def test_warmup_with_kb_store_calls_preload(self):
        """When kb_store is configured, its model is sent to registry.preload()."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        bot = _make_minimal_bot()

        kb_store = MagicMock()
        kb_store._embedding_model_name = "kb-model"
        bot.kb_store = kb_store
        bot.store = None

        with patch.object(registry, "preload", new_callable=AsyncMock) as mock_preload:
            await bot.warmup_embeddings()

        mock_preload.assert_called_once()
        preload_arg = mock_preload.call_args[0][0]
        assert any(m["model_name"] == "kb-model" for m in preload_arg)

    @pytest.mark.asyncio
    async def test_warmup_with_vector_store_calls_preload(self):
        """When store and embedding_model are configured, preload is called."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        bot = _make_minimal_bot()

        store_mock = MagicMock()
        store_mock.connected = True
        bot.store = store_mock
        bot.kb_store = None
        bot.embedding_model = {
            "model_name": "store-model",
            "model_type": "huggingface",
        }

        with patch.object(registry, "preload", new_callable=AsyncMock) as mock_preload:
            await bot.warmup_embeddings()

        mock_preload.assert_called_once()
        preload_arg = mock_preload.call_args[0][0]
        assert any(m["model_name"] == "store-model" for m in preload_arg)

    @pytest.mark.asyncio
    async def test_warmup_preserves_connection_pool_warmup(self):
        """Vector store connection pool warmup still happens."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        bot = _make_minimal_bot()

        store_mock = MagicMock()
        store_mock.connected = False
        store_mock.connection = AsyncMock()
        bot.store = store_mock
        bot.kb_store = None
        bot.embedding_model = None  # no embedding model — no preload

        with patch.object(registry, "preload", new_callable=AsyncMock):
            await bot.warmup_embeddings()

        store_mock.connection.assert_called_once()

    @pytest.mark.asyncio
    async def test_warmup_preserves_kb_document_loading(self):
        """KB document loading still happens for local/custom KBs."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        bot = _make_minimal_bot()
        bot.store = None
        bot.kb_store = None
        bot.embedding_model = None

        kb = MagicMock()
        kb.load_documents = AsyncMock()
        bot.knowledge_bases = [kb]

        with patch.object(registry, "preload", new_callable=AsyncMock):
            await bot.warmup_embeddings()

        kb.load_documents.assert_called_once()

    @pytest.mark.asyncio
    async def test_warmup_collects_both_model_configs(self):
        """Both KB and vector store models are collected for preload."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        bot = _make_minimal_bot()

        kb_store = MagicMock()
        kb_store._embedding_model_name = "kb-model"
        bot.kb_store = kb_store

        store_mock = MagicMock()
        store_mock.connected = True
        bot.store = store_mock
        bot.embedding_model = {
            "model_name": "store-model",
            "model_type": "huggingface",
        }

        with patch.object(registry, "preload", new_callable=AsyncMock) as mock_preload:
            await bot.warmup_embeddings()

        mock_preload.assert_called_once()
        preload_arg = mock_preload.call_args[0][0]
        names = [m["model_name"] for m in preload_arg]
        assert "kb-model" in names
        assert "store-model" in names
