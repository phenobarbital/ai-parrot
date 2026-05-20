"""Pool management unit tests for PostgresFormStorage (FEAT-185).

Covers:
- Construction without pool (self-managed)
- Construction with external pool (backward compat)
- Construction with DSN
- initialize() creates pool when none provided
- initialize() still runs CREATE TABLE DDL
- close() closes self-owned pool
- close() does NOT close externally-provided pool
- close() is idempotent (double-call does not raise)
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

from parrot_formdesigner.services.storage import PostgresFormStorage


class TestPostgresFormStorageConstruction:
    def test_no_pool_construction(self):
        """Can construct without pool; _pool is None, _owns_pool is True."""
        storage = PostgresFormStorage(schema="navigator", table_name="form_schemas")
        assert storage._pool is None
        assert storage._owns_pool is True

    def test_no_pool_no_args(self):
        """Can construct with no arguments at all."""
        storage = PostgresFormStorage()
        assert storage._pool is None
        assert storage._owns_pool is True

    def test_external_pool_construction(self):
        """External pool: _owns_pool is False."""
        mock_pool = MagicMock()
        storage = PostgresFormStorage(pool=mock_pool, schema="navigator")
        assert storage._pool is mock_pool
        assert storage._owns_pool is False

    def test_dsn_stored(self):
        """DSN is stored for later use by initialize()."""
        storage = PostgresFormStorage(dsn="postgresql://user:pw@host/db")
        assert storage._dsn == "postgresql://user:pw@host/db"
        assert storage._pool is None
        assert storage._owns_pool is True

    def test_min_max_size_defaults(self):
        """Default pool sizing values are stored."""
        storage = PostgresFormStorage()
        assert storage._min_size == 2
        assert storage._max_size == 10

    def test_min_max_size_custom(self):
        """Custom pool sizing values are stored."""
        storage = PostgresFormStorage(min_size=5, max_size=20)
        assert storage._min_size == 5
        assert storage._max_size == 20


def _make_mock_pool():
    """Create a properly configured AsyncMock pool for context manager usage."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    # Make acquire() work as an async context manager
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool, mock_conn


class TestPostgresFormStorageInitialize:
    async def test_initialize_creates_pool_when_none(self):
        """initialize() creates asyncpg pool when no pool was provided."""
        storage = PostgresFormStorage(dsn="postgresql://host/db")
        mock_pool, mock_conn = _make_mock_pool()

        # Patch asyncpg in sys.modules since it's imported lazily inside initialize()
        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
        with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
            await storage.initialize()

        assert storage._pool is mock_pool
        mock_asyncpg.create_pool.assert_awaited_once_with(
            dsn="postgresql://host/db",
            min_size=2,
            max_size=10,
        )

    async def test_initialize_with_external_pool_skips_create(self):
        """initialize() does not call create_pool when pool was provided externally."""
        mock_pool, mock_conn = _make_mock_pool()
        storage = PostgresFormStorage(pool=mock_pool)

        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock()
        with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
            await storage.initialize()
            # create_pool should NOT have been called
            mock_asyncpg.create_pool.assert_not_awaited()

        # Pool is still the original external pool
        assert storage._pool is mock_pool


class TestPostgresFormStorageClose:
    async def test_close_self_owned_pool(self):
        """close() closes the pool when _owns_pool is True."""
        storage = PostgresFormStorage(schema="navigator")
        mock_pool = AsyncMock()
        storage._pool = mock_pool
        storage._owns_pool = True

        await storage.close()
        mock_pool.close.assert_awaited_once()
        assert storage._pool is None

    async def test_close_external_pool_noop(self):
        """close() does NOT close an externally-provided pool."""
        mock_pool = AsyncMock()
        storage = PostgresFormStorage(pool=mock_pool)

        await storage.close()
        mock_pool.close.assert_not_called()
        assert storage._pool is None

    async def test_close_idempotent(self):
        """close() twice does not raise."""
        storage = PostgresFormStorage(schema="navigator")
        mock_pool = AsyncMock()
        storage._pool = mock_pool
        storage._owns_pool = True

        await storage.close()
        await storage.close()  # should not raise
        mock_pool.close.assert_awaited_once()  # called only once

    async def test_close_no_pool_noop(self):
        """close() when _pool is None is a no-op."""
        storage = PostgresFormStorage()
        assert storage._pool is None
        # Should not raise
        await storage.close()
        assert storage._pool is None
