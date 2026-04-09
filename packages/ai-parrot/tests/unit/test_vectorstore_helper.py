"""Unit tests for VectorStoreHelper metadata methods."""
import pytest


class TestVectorStoreHelper:
    """Tests for VectorStoreHelper static metadata methods."""

    def test_supported_stores(self):
        """Returns dict of supported stores."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        result = VectorStoreHelper.supported_stores()
        assert isinstance(result, dict)
        assert 'postgres' in result
        assert result['postgres'] == 'PgVectorStore'

    def test_supported_embeddings(self):
        """Returns dict of supported embeddings."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        result = VectorStoreHelper.supported_embeddings()
        assert isinstance(result, dict)
        assert 'huggingface' in result

    def test_supported_loaders(self):
        """Returns clean ext→class_name mapping."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        result = VectorStoreHelper.supported_loaders()
        assert isinstance(result, dict)
        assert '.pdf' in result
        assert result['.pdf'] == 'PDFLoader'
        # Must be string values, NOT tuples
        for ext, cls_name in result.items():
            assert isinstance(cls_name, str), (
                f"{ext} value should be str, got {type(cls_name)}"
            )

    def test_supported_index_types(self):
        """Returns list of DistanceStrategy values."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        result = VectorStoreHelper.supported_index_types()
        assert isinstance(result, list)
        assert 'COSINE' in result
        assert 'EUCLIDEAN_DISTANCE' in result

    def test_supported_stores_all_keys(self):
        """All expected store keys are present."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        result = VectorStoreHelper.supported_stores()
        expected = {'postgres', 'milvus', 'kb', 'faiss_store', 'arango', 'bigquery'}
        assert expected.issubset(set(result.keys()))

    def test_supported_index_types_all_values(self):
        """All DistanceStrategy values are present."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        result = VectorStoreHelper.supported_index_types()
        expected = {'COSINE', 'EUCLIDEAN_DISTANCE', 'MAX_INNER_PRODUCT', 'DOT_PRODUCT', 'JACCARD'}
        assert expected.issubset(set(result))

    def test_supported_embedding_models_returns_list(self):
        """Returns list of embedding model descriptors."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        result = VectorStoreHelper.supported_embedding_models()
        assert isinstance(result, list)
        assert len(result) > 0
        first = result[0]
        assert 'model' in first
        assert 'provider' in first
        assert 'dimension' in first
        assert 'use_case' in first

    def test_supported_embedding_models_filter_by_provider(self):
        """Filtering by provider returns only matching models."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        hf_models = VectorStoreHelper.supported_embedding_models(provider='huggingface')
        assert all(m['provider'] == 'huggingface' for m in hf_models)
        openai_models = VectorStoreHelper.supported_embedding_models(provider='openai')
        assert all(m['provider'] == 'openai' for m in openai_models)
        assert len(openai_models) > 0

    def test_supported_embedding_models_filter_by_use_case(self):
        """Filtering by use_case returns only matching models."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        code_models = VectorStoreHelper.supported_embedding_models(use_case='code')
        assert len(code_models) > 0
        assert all('code' in m['use_case'] for m in code_models)
        retrieval_models = VectorStoreHelper.supported_embedding_models(use_case='retrieval')
        assert len(retrieval_models) > len(code_models)

    def test_supported_embedding_models_combined_filters(self):
        """Provider and use_case filters work together."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        result = VectorStoreHelper.supported_embedding_models(
            provider='huggingface', use_case='multilingual'
        )
        assert all(
            m['provider'] == 'huggingface' and 'multilingual' in m['use_case']
            for m in result
        )

    def test_supported_use_cases(self):
        """Returns dict of use-case descriptions."""
        from parrot.handlers.stores.helpers import VectorStoreHelper
        result = VectorStoreHelper.supported_use_cases()
        assert isinstance(result, dict)
        expected_keys = {'similarity', 'retrieval', 'clustering', 'multilingual', 'code'}
        assert expected_keys == set(result.keys())
