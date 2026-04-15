"""Unit tests for VectorStoreHandler PATCH endpoint (search test)."""
import json
import pytest
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock


def _make_handler_with_request(body: dict):
    """Create a handler with a mocked PATCH request."""
    from parrot.handlers.stores.handler import (
        VectorStoreHandler,
        _STORE_CACHE_KEY,
        _JOB_MANAGER_KEY,
        _TEMP_FILE_KEY,
    )
    handler = VectorStoreHandler.__new__(VectorStoreHandler)
    app = {
        _STORE_CACHE_KEY: OrderedDict(),
        _JOB_MANAGER_KEY: None,
        _TEMP_FILE_KEY: None,
    }
    request = MagicMock()
    request.app = app
    request.json = AsyncMock(return_value=body)
    handler.request = request
    handler.logger = MagicMock()
    return handler


def _make_search_result(content="test content", score=0.9):
    """Create a mock SearchResult."""
    from parrot.stores.models import SearchResult
    return SearchResult(id="1", content=content, score=score)


def _mock_store(exists=True):
    store = MagicMock()
    store._connected = True
    store.collection_exists = AsyncMock(return_value=exists)
    store.similarity_search = AsyncMock(return_value=[])
    store.mmr_search = AsyncMock(return_value=[])
    return store


class TestPatchSearchTest:

    @pytest.mark.asyncio
    async def test_similarity_search(self):
        """Returns similarity search results."""
        result = _make_search_result(content="foo", score=0.95)
        store = _mock_store()
        store.similarity_search = AsyncMock(return_value=[result])

        handler = _make_handler_with_request({
            "query": "test query",
            "table": "t",
            "method": "similarity",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })

        with __import__('unittest.mock', fromlist=['patch']).patch.object(
            handler, "_get_store", AsyncMock(return_value=store)
        ):
            response = await handler.patch()

        data = json.loads(response.text)
        assert data["query"] == "test query"
        assert data["method"] == "similarity"
        assert data["count"] == 1
        assert len(data["results"]) == 1
        store.similarity_search.assert_called_once()
        store.mmr_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_mmr_search(self):
        """Returns MMR search results."""
        result = _make_search_result(content="mmr", score=0.8)
        store = _mock_store()
        store.mmr_search = AsyncMock(return_value=[result])

        handler = _make_handler_with_request({
            "query": "test query",
            "table": "t",
            "method": "mmr",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })

        with __import__('unittest.mock', fromlist=['patch']).patch.object(
            handler, "_get_store", AsyncMock(return_value=store)
        ):
            response = await handler.patch()

        data = json.loads(response.text)
        assert data["method"] == "mmr"
        assert data["count"] == 1
        store.mmr_search.assert_called_once()
        store.similarity_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_both_search(self):
        """Returns combined similarity + MMR results."""
        sim_result = _make_search_result(content="sim", score=0.9)
        mmr_result = _make_search_result(content="mmr", score=0.7)
        store = _mock_store()
        store.similarity_search = AsyncMock(return_value=[sim_result])
        store.mmr_search = AsyncMock(return_value=[mmr_result])

        handler = _make_handler_with_request({
            "query": "test query",
            "table": "t",
            "method": "both",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })

        with __import__('unittest.mock', fromlist=['patch']).patch.object(
            handler, "_get_store", AsyncMock(return_value=store)
        ):
            response = await handler.patch()

        data = json.loads(response.text)
        assert data["method"] == "both"
        assert data["count"] == 2
        store.similarity_search.assert_called_once()
        store.mmr_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_query_returns_400(self):
        """Returns 400 when query is missing."""
        handler = _make_handler_with_request({"table": "t", "vector_store": "postgres"})
        response = await handler.patch()
        assert response.status == 400
        data = json.loads(response.text)
        assert "query" in data["error"]

    @pytest.mark.asyncio
    async def test_invalid_method_returns_400(self):
        """Returns 400 for invalid method value."""
        handler = _make_handler_with_request({
            "query": "q",
            "table": "t",
            "method": "fuzz",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })
        response = await handler.patch()
        assert response.status == 400
        data = json.loads(response.text)
        assert "method" in data["error"].lower() or "Invalid" in data["error"]

    @pytest.mark.asyncio
    async def test_collection_not_found_returns_404(self):
        """Returns 404 when collection doesn't exist."""
        store = _mock_store(exists=False)

        handler = _make_handler_with_request({
            "query": "q",
            "table": "missing_table",
            "method": "similarity",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })

        with __import__('unittest.mock', fromlist=['patch']).patch.object(
            handler, "_get_store", AsyncMock(return_value=store)
        ):
            response = await handler.patch()

        assert response.status == 404

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """Returns 200 with empty results, not an error."""
        store = _mock_store()
        store.similarity_search = AsyncMock(return_value=[])

        handler = _make_handler_with_request({
            "query": "q",
            "table": "t",
            "method": "similarity",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })

        with __import__('unittest.mock', fromlist=['patch']).patch.object(
            handler, "_get_store", AsyncMock(return_value=store)
        ):
            response = await handler.patch()

        assert response.status == 200
        data = json.loads(response.text)
        assert data["count"] == 0
        assert data["results"] == []
