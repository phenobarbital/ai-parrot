"""Tests for AbstractStore registry integration (TASK-376)."""
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


def _make_concrete_store():
    """Return a minimal concrete AbstractStore subclass for testing."""
    from parrot.stores.abstract import AbstractStore

    class ConcreteStore(AbstractStore):
        async def search(self, *a, **kw):
            return []

        async def add_documents(self, *a, **kw):
            pass

        async def prepare_embedding_table(self, *a, **kw):
            pass

        async def delete_documents(self, *a, **kw):
            pass

        async def connection(self):
            pass

        async def disconnect(self):
            pass

    return ConcreteStore()


class TestAbstractStoreRegistryIntegration:
    def test_create_embedding_uses_registry(self):
        """create_embedding() delegates to EmbeddingRegistry.get_or_create_sync()."""
        from parrot.embeddings.registry import EmbeddingRegistry

        store = _make_concrete_store()
        mock_model = MagicMock()

        registry = EmbeddingRegistry.instance(max_models=10)
        with patch.object(registry, "get_or_create_sync", return_value=mock_model) as mock_get:
            result = store.create_embedding(
                {"model_name": "all-MiniLM-L6-v2", "model_type": "huggingface"}
            )

        mock_get.assert_called_once_with("all-MiniLM-L6-v2", "huggingface")
        assert result is mock_model

    def test_same_config_returns_same_instance(self):
        """Two calls with same config return the same cached instance."""
        store = _make_concrete_store()
        mock_model = MagicMock()

        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        with patch.object(registry, "_build_model", return_value=mock_model):
            m1 = store.create_embedding(
                {"model_name": "all-MiniLM-L6-v2", "model_type": "huggingface"}
            )
            m2 = store.create_embedding(
                {"model_name": "all-MiniLM-L6-v2", "model_type": "huggingface"}
            )

        assert m1 is m2

    def test_create_embedding_raises_on_unsupported_type(self):
        """create_embedding() raises ConfigError for unknown model_type."""
        from parrot.exceptions import ConfigError

        store = _make_concrete_store()
        with pytest.raises(ConfigError):
            store.create_embedding({"model_type": "unknown-backend"})

    def test_get_default_embedding_uses_registry(self):
        """get_default_embedding() also goes through the registry."""
        from parrot.embeddings.registry import EmbeddingRegistry

        store = _make_concrete_store()
        mock_model = MagicMock()

        registry = EmbeddingRegistry.instance(max_models=10)
        with patch.object(registry, "get_or_create_sync", return_value=mock_model) as mock_get:
            result = store.get_default_embedding()

        assert mock_get.called
        assert result is mock_model

    def test_generate_embedding_works(self):
        """generate_embedding() still produces embeddings via the cached model."""
        from parrot.embeddings.registry import EmbeddingRegistry

        store = _make_concrete_store()
        mock_model = MagicMock()
        mock_model.embed_documents.return_value = [[0.1, 0.2, 0.3]]

        registry = EmbeddingRegistry.instance(max_models=10)
        with patch.object(registry, "_build_model", return_value=mock_model):
            result = store.generate_embedding(["hello world"])

        mock_model.embed_documents.assert_called_once_with(["hello world"])
        assert result == [[0.1, 0.2, 0.3]]
