"""Tests for EmbeddingModel base registry integration (TASK-379)."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset EmbeddingRegistry singleton between tests."""
    from parrot.embeddings.registry import EmbeddingRegistry

    EmbeddingRegistry._instance = None
    yield
    if EmbeddingRegistry._instance is not None:
        EmbeddingRegistry._instance.clear()
        EmbeddingRegistry._instance = None


def _make_concrete_embedding_model(class_name: str = "SentenceTransformerModel", model_name: str = "test-model"):
    """Create a minimal concrete EmbeddingModel subclass for testing."""
    import numpy as np
    from parrot.embeddings.base import EmbeddingModel

    class ConcreteModel(EmbeddingModel):
        def _create_embedding(self, model_name: str, **kwargs):
            m = MagicMock()
            m.model_name = model_name
            return m

        async def encode(self, texts, **kwargs):
            return np.zeros((len(texts), 384))

    # Override class name for testing
    ConcreteModel.__name__ = class_name

    return ConcreteModel(model_name=model_name)


class TestEmbeddingModelRegistryIntegration:
    def test_model_property_uses_registry(self):
        """model property delegates to registry when available."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        mock_cached = MagicMock()

        embedding = _make_concrete_embedding_model("SentenceTransformerModel", "all-MiniLM-L6-v2")

        with patch.object(registry, "get_or_create_sync", return_value=mock_cached) as mock_get:
            result = embedding.model

        mock_get.assert_called_once_with("all-MiniLM-L6-v2", "huggingface")
        assert result is mock_cached

    def test_model_property_fallback_on_registry_exception(self):
        """model property falls back to _create_embedding() if registry raises."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        fallback_model = MagicMock()

        embedding = _make_concrete_embedding_model("SentenceTransformerModel", "all-MiniLM-L6-v2")
        embedding._create_embedding = MagicMock(return_value=fallback_model)

        with patch.object(registry, "get_or_create_sync", side_effect=RuntimeError("fail")):
            result = embedding.model

        assert result is fallback_model
        embedding._create_embedding.assert_called_once()

    def test_get_model_type_huggingface(self):
        """SentenceTransformerModel maps to 'huggingface'."""
        embedding = _make_concrete_embedding_model("SentenceTransformerModel")
        assert embedding._get_model_type() == "huggingface"

    def test_get_model_type_openai(self):
        """OpenAIEmbeddingModel maps to 'openai'."""
        embedding = _make_concrete_embedding_model("OpenAIEmbeddingModel")
        assert embedding._get_model_type() == "openai"

    def test_get_model_type_google(self):
        """GoogleEmbeddingModel maps to 'google'."""
        embedding = _make_concrete_embedding_model("GoogleEmbeddingModel")
        assert embedding._get_model_type() == "google"

    def test_get_model_type_unknown_defaults_to_huggingface(self):
        """Unknown subclass names fall back to 'huggingface'."""
        embedding = _make_concrete_embedding_model("SomeUnknownModel")
        assert embedding._get_model_type() == "huggingface"

    def test_model_property_caches_on_instance(self):
        """Second access to .model returns same object without re-querying registry."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        mock_cached = MagicMock()
        call_count = 0

        def _get_or_create_sync(model_name, model_type, **_kw):
            nonlocal call_count
            call_count += 1
            return mock_cached

        embedding = _make_concrete_embedding_model("SentenceTransformerModel")

        with patch.object(registry, "get_or_create_sync", side_effect=_get_or_create_sync):
            _ = embedding.model
            _ = embedding.model  # second access

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_initialize_model_uses_registry_async_path(self):
        """initialize_model() uses registry's async get_or_create()."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        mock_cached = MagicMock()

        embedding = _make_concrete_embedding_model("SentenceTransformerModel", "all-MiniLM-L6-v2")

        with patch.object(registry, "get_or_create", new_callable=AsyncMock, return_value=mock_cached) as mock_get:
            await embedding.initialize_model()

        mock_get.assert_called_once_with("all-MiniLM-L6-v2", "huggingface")
        assert embedding._model is mock_cached

    @pytest.mark.asyncio
    async def test_initialize_model_fallback_on_exception(self):
        """initialize_model() falls back to _create_embedding() if registry raises."""
        from parrot.embeddings.registry import EmbeddingRegistry

        registry = EmbeddingRegistry.instance(max_models=10)
        fallback_model = MagicMock()

        embedding = _make_concrete_embedding_model("SentenceTransformerModel")
        embedding._create_embedding = MagicMock(return_value=fallback_model)

        with patch.object(registry, "get_or_create", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            await embedding.initialize_model()

        assert embedding._model is fallback_model
