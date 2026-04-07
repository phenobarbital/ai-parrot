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
