"""Tests for KnowledgeBaseStore registry integration (TASK-377)."""
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset EmbeddingRegistry singleton between tests."""
    from parrot.embeddings.registry import EmbeddingRegistry

    EmbeddingRegistry._instance = None
    yield
    if EmbeddingRegistry._instance is not None:
        EmbeddingRegistry._instance.clear()
        EmbeddingRegistry._instance = None


def _mock_faiss():
    """Return a patch context for faiss so tests can run without it installed."""
    faiss_mock = MagicMock()
    faiss_mock.IndexFlatIP = MagicMock(return_value=MagicMock())
    faiss_mock.IndexHNSWFlat = MagicMock(return_value=MagicMock())
    faiss_mock.METRIC_INNER_PRODUCT = 0
    return patch.dict("sys.modules", {"faiss": faiss_mock})


class TestKBStoreRegistryIntegration:
    def test_init_does_not_load_model(self):
        """KnowledgeBaseStore.__init__ does NOT trigger model loading."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)

        with _mock_faiss(), \
             patch.object(registry, "_build_model") as builder:
            from parrot.stores.kb.store import KnowledgeBaseStore
            kb = KnowledgeBaseStore(embedding_model="all-MiniLM-L6-v2")

        builder.assert_not_called()
        # Internal state is set up
        assert kb._embedding_model_name == "all-MiniLM-L6-v2"
        assert kb._embeddings is None

    def test_embeddings_property_loads_on_first_access(self):
        """Accessing .embeddings triggers registry lookup."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        mock_model = MagicMock()

        with _mock_faiss():
            from parrot.stores.kb.store import KnowledgeBaseStore
            kb = KnowledgeBaseStore(embedding_model="all-MiniLM-L6-v2")

        with patch.object(registry, "_build_model", return_value=mock_model):
            result = kb.embeddings

        assert result is mock_model
        assert kb._embeddings is mock_model  # cached on instance

    def test_embeddings_property_cached_on_instance(self):
        """Second access to .embeddings returns same object without re-loading."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        mock_model = MagicMock()
        call_count = 0

        def _build(model_name, model_type, **_kw):
            nonlocal call_count
            call_count += 1
            return mock_model

        with _mock_faiss():
            from parrot.stores.kb.store import KnowledgeBaseStore
            kb = KnowledgeBaseStore(embedding_model="all-MiniLM-L6-v2")

        with patch.object(registry, "_build_model", side_effect=_build):
            _ = kb.embeddings
            _ = kb.embeddings  # second access

        assert call_count == 1

    def test_two_kbstores_share_model(self):
        """Two KBStores with same model name get the same registry instance."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        mock_model = MagicMock()

        with _mock_faiss():
            from parrot.stores.kb.store import KnowledgeBaseStore
            kb1 = KnowledgeBaseStore(embedding_model="all-MiniLM-L6-v2")
            kb2 = KnowledgeBaseStore(embedding_model="all-MiniLM-L6-v2")

        with patch.object(registry, "_build_model", return_value=mock_model):
            m1 = kb1.embeddings
            m2 = kb2.embeddings

        assert m1 is m2

    @pytest.mark.asyncio
    async def test_add_facts_triggers_lazy_load(self):
        """add_facts() causes embedding model to load (via .embeddings property)."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((1, 384), dtype=np.float32)

        with _mock_faiss():
            from parrot.stores.kb.store import KnowledgeBaseStore
            kb = KnowledgeBaseStore(embedding_model="all-MiniLM-L6-v2")

        with patch.object(registry, "_build_model", return_value=mock_model):
            await kb.add_facts([{"content": "Test fact", "metadata": {}}])

        mock_model.encode.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_facts_triggers_lazy_load(self):
        """search_facts() causes embedding model to load."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((1, 384), dtype=np.float32)

        with _mock_faiss() as faiss_mock_ctx:
            from parrot.stores.kb.store import KnowledgeBaseStore
            kb = KnowledgeBaseStore(embedding_model="all-MiniLM-L6-v2")
            # Patch the index.search to return empty results
            kb.index.search = MagicMock(
                return_value=(np.array([[]], dtype=np.float32), np.array([[-1]], dtype=np.int64))
            )

        with patch.object(registry, "_build_model", return_value=mock_model):
            results = await kb.search_facts("test query")

        mock_model.encode.assert_called_once()
        assert isinstance(results, list)

    def test_embeddings_setter_for_backwards_compat(self):
        """Direct assignment to .embeddings still works."""
        with _mock_faiss():
            from parrot.stores.kb.store import KnowledgeBaseStore
            kb = KnowledgeBaseStore(embedding_model="all-MiniLM-L6-v2")

        mock_model = MagicMock()
        kb.embeddings = mock_model
        assert kb._embeddings is mock_model
        assert kb.embeddings is mock_model
