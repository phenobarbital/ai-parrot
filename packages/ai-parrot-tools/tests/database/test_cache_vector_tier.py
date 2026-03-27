import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.database.cache import SchemaMetadataCache
from parrot.tools.database.models import TableMetadata


def make_table_meta(schema="public", tablename="users"):
    return TableMetadata(
        schema=schema,
        tablename=tablename,
        table_type="BASE TABLE",
        full_name=f'"{schema}"."{tablename}"',
        comment="Test table",
        columns=[{"name": "id", "type": "integer", "nullable": False}],
        primary_keys=["id"],
    )


def test_cache_auto_creates_faiss_store():
    """Auto-creation of FAISSStore when no vector_store provided."""
    try:
        import faiss  # noqa: F401
        cache = SchemaMetadataCache()
        assert cache.vector_enabled is True
        assert cache.vector_store is not None
    except ImportError:
        pytest.skip("faiss-cpu not installed")


def test_cache_lru_only_without_faiss():
    """Falls back to LRU-only mode when FAISSStore creation fails."""
    with patch(
        "parrot.tools.database.cache._try_create_faiss_store", return_value=None
    ):
        cache = SchemaMetadataCache()
        assert cache.vector_enabled is False


@pytest.mark.asyncio
async def test_store_calls_add_documents():
    """_store_in_vector_store calls add_documents on the vector store."""
    mock_store = AsyncMock()
    mock_store.add_documents = AsyncMock()

    cache = SchemaMetadataCache(vector_store=mock_store)
    meta = make_table_meta()
    await cache._store_in_vector_store(meta)

    mock_store.add_documents.assert_called_once()
    docs = mock_store.add_documents.call_args[0][0]
    assert len(docs) == 1
    # The Document has page_content attribute
    assert "users" in docs[0].page_content


@pytest.mark.asyncio
async def test_convert_vector_results_roundtrip():
    """_convert_vector_results parses YAML content back into TableMetadata."""
    cache = SchemaMetadataCache.__new__(SchemaMetadataCache)
    cache.logger = logging.getLogger("test")

    meta = make_table_meta()
    yaml_content = meta.to_yaml_context()

    fake_result = {
        "content": yaml_content,
        "metadata": {
            "schema_name": "public",
            "tablename": "users",
            "table_type": "BASE TABLE",
            "full_name": '"public"."users"',
        },
    }

    results = await cache._convert_vector_results([fake_result])
    assert len(results) == 1
    assert results[0].tablename == "users"
    assert results[0].schema == "public"


@pytest.mark.asyncio
async def test_search_falls_back_to_lru_on_vector_error():
    """search_similar_tables falls back to _search_cache_only on vector store error."""
    mock_store = AsyncMock()
    mock_store.similarity_search = AsyncMock(side_effect=RuntimeError("store down"))

    cache = SchemaMetadataCache(vector_store=mock_store)
    # Should not raise; falls back to cache-only (empty result)
    results = await cache.search_similar_tables(["public"], "users", limit=5)
    assert isinstance(results, list)
