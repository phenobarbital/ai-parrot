"""Unit tests for VectorStoreHandler store cache and lifecycle."""
import pytest
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch


def _make_handler(cache=None, job_manager=None, temp_file_manager=None):
    """Create a VectorStoreHandler-like object with mocked request/app."""
    from parrot.handlers.stores.handler import (
        VectorStoreHandler,
        _JOB_MANAGER_KEY,
        _TEMP_FILE_KEY,
        _STORE_CACHE_KEY,
    )
    handler = VectorStoreHandler.__new__(VectorStoreHandler)
    app = {
        _STORE_CACHE_KEY: cache if cache is not None else OrderedDict(),
        _JOB_MANAGER_KEY: job_manager,
        _TEMP_FILE_KEY: temp_file_manager,
    }
    request = MagicMock()
    request.app = app
    handler._request = request
    handler.logger = MagicMock()
    return handler


def _make_store_config(**kwargs):
    from parrot.stores.models import StoreConfig
    defaults = {
        "vector_store": "postgres",
        "table": "test_table",
        "schema": "public",
        "embedding_model": {"model": "thenlper/gte-base", "model_type": "huggingface"},
        "dimension": 768,
        "dsn": "postgresql+asyncpg://test/testdb",
    }
    defaults.update(kwargs)
    return StoreConfig(**defaults)


# Canonical embed token for the default gte-base config used by
# _make_store_config() — mirrors VectorStoreHandler._embedding_cache_token.
_DEFAULT_EMBED_TOKEN = (
    ("model", "thenlper/gte-base"),
    ("model_type", "huggingface"),
)
_DEFAULT_METRIC_TOKEN = "COSINE"
_DEFAULT_DISTANCE_TOKEN = "COSINE"


def _cache_key(store_type="postgres", dsn="postgresql+asyncpg://test/testdb"):
    return (
        store_type,
        dsn,
        _DEFAULT_EMBED_TOKEN,
        _DEFAULT_METRIC_TOKEN,
        _DEFAULT_DISTANCE_TOKEN,
    )


class TestStoreConnectionCache:
    @pytest.mark.asyncio
    async def test_cache_miss_instantiates_and_connects(self):
        """First call for a config creates store and calls connection()."""
        mock_store = MagicMock()
        mock_store._connected = True
        mock_store.connection = AsyncMock(return_value=(None, None))

        mock_cls = MagicMock(return_value=mock_store)
        mock_module = MagicMock()
        mock_module.PgVectorStore = mock_cls

        handler = _make_handler()
        config = _make_store_config()

        with patch("importlib.import_module", return_value=mock_module):
            store = await handler._get_store(config)

        mock_store.connection.assert_called_once()
        assert store is mock_store

    @pytest.mark.asyncio
    async def test_cache_hit_returns_same_instance(self):
        """Second call with same config returns cached store."""
        mock_store = MagicMock()
        mock_store._connected = True
        mock_store.connection = AsyncMock()

        cache = OrderedDict()
        cache[_cache_key()] = mock_store

        handler = _make_handler(cache=cache)
        config = _make_store_config()

        store = await handler._get_store(config)

        mock_store.connection.assert_not_called()
        assert store is mock_store

    @pytest.mark.asyncio
    async def test_cache_miss_on_embedding_model_change(self):
        """Switching embedding_model must miss the cache and build a new store.

        Regression: previously the cache key was only (store_type, dsn),
        so a second call with e5-large returned a cached gte-base store,
        triggering ``pgvector: expected 1024 dimensions, not 768`` on
        add_documents().
        """
        cached_store = MagicMock()
        cached_store._connected = True
        cached_store.connection = AsyncMock()

        cache = OrderedDict()
        cache[_cache_key()] = cached_store

        # New store returned when we switch to e5-large
        new_store = MagicMock()
        new_store._connected = True
        new_store.connection = AsyncMock()

        mock_cls = MagicMock(return_value=new_store)
        mock_module = MagicMock()
        mock_module.PgVectorStore = mock_cls

        handler = _make_handler(cache=cache)
        config = _make_store_config(
            embedding_model={
                "model": "intfloat/e5-large-v2",
                "model_type": "huggingface",
            },
            dimension=1024,
        )

        with patch("importlib.import_module", return_value=mock_module):
            store = await handler._get_store(config)

        # Cache miss → new store instantiated and connected
        new_store.connection.assert_called_once()
        # Old gte-base store must NOT have been returned
        assert store is new_store
        cached_store.connection.assert_not_called()
        # Both entries now live in the cache, keyed by their embedding token
        assert len(cache) == 2

    @pytest.mark.asyncio
    async def test_cache_miss_on_metric_change(self):
        """Switching metric/distance strategy must miss the cache."""
        cached_store = MagicMock()
        cached_store._connected = True
        cached_store.connection = AsyncMock()

        cache = OrderedDict()
        cache[_cache_key()] = cached_store

        new_store = MagicMock()
        new_store._connected = True
        new_store.connection = AsyncMock()

        mock_cls = MagicMock(return_value=new_store)
        mock_module = MagicMock()
        mock_module.PgVectorStore = mock_cls

        handler = _make_handler(cache=cache)
        config = _make_store_config(metric_type="L2", distance_strategy="L2")

        with patch("importlib.import_module", return_value=mock_module):
            store = await handler._get_store(config)

        assert store is new_store
        cached_store.connection.assert_not_called()
        new_store.connection.assert_called_once()
        assert len(cache) == 2
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["metric_type"] == "L2"
        assert call_kwargs["distance_strategy"] == "L2"

    @pytest.mark.asyncio
    async def test_cache_eviction_disconnects_oldest(self):
        """When cache is full, oldest entry is evicted and disconnected."""
        from parrot.handlers.stores.handler import _STORE_CACHE_MAX

        evicted_store = MagicMock()
        evicted_store._connected = True
        evicted_store.disconnect = AsyncMock()

        new_store = MagicMock()
        new_store._connected = True
        new_store.connection = AsyncMock()

        # Fill cache to max — each entry uses the full metric-aware key shape
        cache = OrderedDict()
        cache[_cache_key(dsn="evicted")] = evicted_store
        for i in range(1, _STORE_CACHE_MAX):
            m = MagicMock()
            m._connected = True
            cache[_cache_key(dsn=f"dsn_{i}")] = m

        assert len(cache) == _STORE_CACHE_MAX

        mock_cls = MagicMock(return_value=new_store)
        mock_module = MagicMock()
        mock_module.PgVectorStore = mock_cls

        handler = _make_handler(cache=cache)
        config = _make_store_config(dsn="postgresql+asyncpg://new/db")

        with patch("importlib.import_module", return_value=mock_module):
            await handler._get_store(config)

        evicted_store.disconnect.assert_called_once()
        assert _cache_key(dsn="evicted") not in cache

    @pytest.mark.asyncio
    async def test_cache_reconnects_stale_store(self):
        """Cache hit with _connected=False triggers connection()."""
        stale_store = MagicMock()
        stale_store._connected = False
        stale_store.connection = AsyncMock()

        cache = OrderedDict()
        cache[_cache_key()] = stale_store

        handler = _make_handler(cache=cache)
        config = _make_store_config()

        store = await handler._get_store(config)

        stale_store.connection.assert_called_once()
        assert store is stale_store

    @pytest.mark.asyncio
    async def test_postgres_dsn_fallback(self):
        """Postgres store with no DSN uses async_default_dsn."""
        from parrot.conf import async_default_dsn

        mock_store = MagicMock()
        mock_store._connected = True
        mock_store.connection = AsyncMock()

        mock_cls = MagicMock(return_value=mock_store)
        mock_module = MagicMock()
        mock_module.PgVectorStore = mock_cls

        handler = _make_handler()
        # No DSN provided
        config = _make_store_config(dsn=None)

        with patch("importlib.import_module", return_value=mock_module):
            await handler._get_store(config)

        # Should have been instantiated with the default DSN
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs.get("dsn") == async_default_dsn

    @pytest.mark.asyncio
    async def test_bigquery_schema_to_dataset(self):
        """BigQuery store maps schema to dataset param."""
        mock_store = MagicMock()
        mock_store._connected = True
        mock_store.connection = AsyncMock()

        mock_cls = MagicMock(return_value=mock_store)
        mock_module = MagicMock()
        mock_module.BigQueryStore = mock_cls

        handler = _make_handler()
        config = _make_store_config(vector_store="bigquery", schema="my_dataset", dsn=None)

        with patch("importlib.import_module", return_value=mock_module):
            await handler._get_store(config)

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs.get("dataset") == "my_dataset"
        assert "schema" not in call_kwargs


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_cleanup_disconnects_all_stores(self):
        """_on_cleanup calls disconnect() on every cached store."""
        from parrot.handlers.stores.handler import (
            VectorStoreHandler,
            _STORE_CACHE_KEY,
            _JOB_MANAGER_KEY,
            _TEMP_FILE_KEY,
        )

        store1 = MagicMock()
        store1.disconnect = AsyncMock()
        store2 = MagicMock()
        store2.disconnect = AsyncMock()

        cache = OrderedDict()
        cache[_cache_key(dsn="dsn1")] = store1
        cache[_cache_key(dsn="dsn2")] = store2

        mock_jm = MagicMock()
        mock_jm.stop = AsyncMock()
        mock_tfm = MagicMock()
        mock_tfm.cleanup = MagicMock()

        app = {
            _STORE_CACHE_KEY: cache,
            _JOB_MANAGER_KEY: mock_jm,
            _TEMP_FILE_KEY: mock_tfm,
        }

        await VectorStoreHandler._on_cleanup(app)

        store1.disconnect.assert_called_once()
        store2.disconnect.assert_called_once()
        assert len(cache) == 0

    @pytest.mark.asyncio
    async def test_cleanup_handles_disconnect_errors(self):
        """_on_cleanup continues if one store.disconnect() raises."""
        from parrot.handlers.stores.handler import (
            VectorStoreHandler,
            _STORE_CACHE_KEY,
            _JOB_MANAGER_KEY,
            _TEMP_FILE_KEY,
        )

        store1 = MagicMock()
        store1.disconnect = AsyncMock(side_effect=RuntimeError("oops"))
        store2 = MagicMock()
        store2.disconnect = AsyncMock()

        cache = OrderedDict()
        cache[_cache_key(dsn="dsn1")] = store1
        cache[_cache_key(dsn="dsn2")] = store2

        mock_jm = MagicMock()
        mock_jm.stop = AsyncMock()
        mock_tfm = MagicMock()
        mock_tfm.cleanup = MagicMock()

        app = {
            _STORE_CACHE_KEY: cache,
            _JOB_MANAGER_KEY: mock_jm,
            _TEMP_FILE_KEY: mock_tfm,
        }

        # Should not raise even though store1 fails
        await VectorStoreHandler._on_cleanup(app)

        store1.disconnect.assert_called_once()
        store2.disconnect.assert_called_once()
