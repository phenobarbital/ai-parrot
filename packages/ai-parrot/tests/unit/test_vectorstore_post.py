"""Unit tests for VectorStoreHandler POST endpoint (create collection)."""
import json
import pytest
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch


def _make_handler_with_request(body: dict, cache=None):
    """Create a handler with a mocked POST request."""
    from parrot.handlers.stores.handler import (
        VectorStoreHandler,
        _STORE_CACHE_KEY,
        _JOB_MANAGER_KEY,
        _TEMP_FILE_KEY,
    )
    handler = VectorStoreHandler.__new__(VectorStoreHandler)
    app = {
        _STORE_CACHE_KEY: cache if cache is not None else OrderedDict(),
        _JOB_MANAGER_KEY: None,
        _TEMP_FILE_KEY: None,
    }
    request = MagicMock()
    request.app = app
    request.json = AsyncMock(return_value=body)
    handler.request = request
    handler.logger = MagicMock()
    return handler


def _mock_store(exists=False):
    """Return a mock AbstractStore."""
    store = MagicMock()
    store._connected = True
    store.collection_exists = AsyncMock(return_value=exists)
    store.delete_collection = AsyncMock()
    store.create_collection = AsyncMock()
    store.prepare_embedding_table = AsyncMock()
    return store


class TestPostCreateCollection:

    @pytest.mark.asyncio
    async def test_create_new_collection(self):
        """Creates collection when it doesn't exist."""
        store = _mock_store(exists=False)
        handler = _make_handler_with_request({
            "table": "test_table",
            "schema": "public",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })

        with patch.object(handler, "_get_store", AsyncMock(return_value=store)):
            response = await handler.post()

        data = json.loads(response.text)
        assert data["status"] == "created"
        assert data["table"] == "test_table"
        store.create_collection.assert_called_once()
        store.prepare_embedding_table.assert_called_once()
        store.delete_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_recreate_existing_collection(self):
        """Drops and recreates when no_drop_table=false (default)."""
        store = _mock_store(exists=True)
        handler = _make_handler_with_request({
            "table": "existing_table",
            "schema": "public",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
            "no_drop_table": False,
        })

        with patch.object(handler, "_get_store", AsyncMock(return_value=store)):
            response = await handler.post()

        data = json.loads(response.text)
        assert data["status"] == "created"
        store.delete_collection.assert_called_once()
        store.create_collection.assert_called_once()
        store.prepare_embedding_table.assert_called_once()

    @pytest.mark.asyncio
    async def test_prepare_only_no_drop(self):
        """Only prepares embedding table when no_drop_table=true."""
        store = _mock_store(exists=True)
        handler = _make_handler_with_request({
            "table": "existing_table",
            "schema": "public",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
            "no_drop_table": True,
        })

        with patch.object(handler, "_get_store", AsyncMock(return_value=store)):
            response = await handler.post()

        data = json.loads(response.text)
        assert data["status"] == "created"
        store.delete_collection.assert_not_called()
        store.create_collection.assert_not_called()
        store.prepare_embedding_table.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_table_returns_400(self):
        """Returns 400 when table field is missing."""
        handler = _make_handler_with_request({
            "vector_store": "postgres",
        })
        response = await handler.post()
        assert response.status == 400
        data = json.loads(response.text)
        assert "table" in data["error"]

    @pytest.mark.asyncio
    async def test_unsupported_store_returns_400(self):
        """Returns 400 for unknown vector_store type."""
        handler = _make_handler_with_request({
            "table": "t",
            "vector_store": "unknown_store",
        })
        response = await handler.post()
        assert response.status == 400
        data = json.loads(response.text)
        assert "Unsupported" in data["error"]

    @pytest.mark.asyncio
    async def test_store_error_returns_500(self):
        """Returns 500 when store operation raises."""
        store = _mock_store(exists=False)
        store.create_collection = AsyncMock(side_effect=RuntimeError("DB error"))
        handler = _make_handler_with_request({
            "table": "test_table",
            "vector_store": "postgres",
            "dsn": "postgresql+asyncpg://test/db",
        })

        with patch.object(handler, "_get_store", AsyncMock(return_value=store)):
            response = await handler.post()

        assert response.status == 500
        data = json.loads(response.text)
        assert "DB error" in data["error"]
