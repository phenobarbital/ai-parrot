"""Unit tests for source-layer test_connection() overrides.

Covers the non-SQL driver overrides added in FEAT-136 TASK-933:
- MongoSource: ping command
- DocumentDBSource: inherits MongoSource ping
- AtlasSource: inherits MongoSource ping
- ElasticSource: info() call
- InfluxSource: buckets() query

Part of FEAT-136 — database-toolkit-parity, TASK-933.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_async_context_manager(conn_mock):
    """Return a mock that works as ``async with await db.connection() as conn``."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn_mock)
    cm.__aexit__ = AsyncMock(return_value=False)

    async def _connection():
        return cm

    return _connection


# ---------------------------------------------------------------------------
# MongoSource
# ---------------------------------------------------------------------------


class TestMongoTestConnection:
    """Tests for MongoSource.test_connection() — MongoDB ping command."""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        from parrot.tools.databasequery.sources.mongodb import MongoSource

        source = MongoSource()
        mongo_client = AsyncMock()
        mongo_client.admin.command = AsyncMock(return_value={"ok": 1})

        conn_mock = MagicMock()
        conn_mock._connection = mongo_client

        mock_db = MagicMock()
        mock_db.connection = _make_async_context_manager(conn_mock)

        # Patch _get_connection — the method test_connection() calls directly.
        # (Do NOT patch _get_db here; test_connection calls _get_connection,
        # which internally calls _get_db. Patching the wrong layer makes the
        # test fragile and will silently miss future indirection.)
        with patch.object(source, "_get_connection", return_value=mock_db):
            result = await source.test_connection({"host": "localhost"})

        assert result is True
        mongo_client.admin.command.assert_awaited_once_with("ping")

    @pytest.mark.asyncio
    async def test_returns_false_on_connection_failure(self) -> None:
        from parrot.tools.databasequery.sources.mongodb import MongoSource

        source = MongoSource()
        with patch.object(source, "_get_connection", side_effect=Exception("connection refused")):
            result = await source.test_connection({"host": "badhost"})

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_ping_raises(self) -> None:
        from parrot.tools.databasequery.sources.mongodb import MongoSource

        source = MongoSource()
        mongo_client = AsyncMock()
        mongo_client.admin.command = AsyncMock(side_effect=Exception("auth failed"))

        conn_mock = MagicMock()
        conn_mock._connection = mongo_client

        mock_db = MagicMock()
        mock_db.connection = _make_async_context_manager(conn_mock)

        with patch.object(source, "_get_connection", return_value=mock_db):
            result = await source.test_connection({"host": "localhost"})

        assert result is False

    @pytest.mark.asyncio
    async def test_never_raises(self) -> None:
        from parrot.tools.databasequery.sources.mongodb import MongoSource

        source = MongoSource()
        with patch.object(source, "_get_connection", side_effect=RuntimeError("crash")):
            # Must not raise
            result = await source.test_connection({})

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_returns_bool_type(self) -> None:
        from parrot.tools.databasequery.sources.mongodb import MongoSource

        source = MongoSource()
        with patch.object(source, "_get_connection", side_effect=Exception("fail")):
            result = await source.test_connection({})

        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# DocumentDBSource — inherits MongoSource.test_connection
# ---------------------------------------------------------------------------


class TestDocumentDBTestConnection:
    """DocumentDBSource inherits test_connection from MongoSource."""

    @pytest.mark.asyncio
    async def test_inherits_mongo_test_connection(self) -> None:
        """DocumentDBSource should have test_connection from MongoSource."""
        from parrot.tools.databasequery.sources.documentdb import DocumentDBSource

        src = DocumentDBSource()
        # Verify test_connection is inherited (not directly defined on DocumentDBSource)
        assert "test_connection" not in DocumentDBSource.__dict__, (
            "DocumentDBSource should inherit test_connection, not define its own"
        )
        # Verify it IS available (inherited)
        assert hasattr(src, "test_connection")

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self) -> None:
        from parrot.tools.databasequery.sources.documentdb import DocumentDBSource

        src = DocumentDBSource()
        with patch.object(src, "_get_connection", side_effect=Exception("ssl error")):
            result = await src.test_connection({"host": "docdb.host", "ssl": True})

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        from parrot.tools.databasequery.sources.documentdb import DocumentDBSource

        src = DocumentDBSource()
        mongo_client = AsyncMock()
        mongo_client.admin.command = AsyncMock(return_value={"ok": 1})

        conn_mock = MagicMock()
        conn_mock._connection = mongo_client

        mock_db = MagicMock()
        mock_db.connection = _make_async_context_manager(conn_mock)

        with patch.object(src, "_get_connection", return_value=mock_db):
            result = await src.test_connection({"host": "docdb.host"})

        assert result is True


# ---------------------------------------------------------------------------
# AtlasSource — inherits MongoSource.test_connection
# ---------------------------------------------------------------------------


class TestAtlasTestConnection:
    """AtlasSource inherits test_connection from MongoSource."""

    @pytest.mark.asyncio
    async def test_inherits_mongo_test_connection(self) -> None:
        """AtlasSource should have test_connection from MongoSource."""
        from parrot.tools.databasequery.sources.atlas import AtlasSource

        src = AtlasSource()
        assert "test_connection" not in AtlasSource.__dict__, (
            "AtlasSource should inherit test_connection, not define its own"
        )
        assert hasattr(src, "test_connection")

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self) -> None:
        from parrot.tools.databasequery.sources.atlas import AtlasSource

        src = AtlasSource()
        with patch.object(src, "_get_connection", side_effect=Exception("network error")):
            result = await src.test_connection({"dsn": "mongodb+srv://bad.host/db"})

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        from parrot.tools.databasequery.sources.atlas import AtlasSource

        src = AtlasSource()
        mongo_client = AsyncMock()
        mongo_client.admin.command = AsyncMock(return_value={"ok": 1})

        conn_mock = MagicMock()
        conn_mock._connection = mongo_client

        mock_db = MagicMock()
        mock_db.connection = _make_async_context_manager(conn_mock)

        with patch.object(src, "_get_connection", return_value=mock_db):
            result = await src.test_connection({"dsn": "mongodb+srv://cluster.mongodb.net/db"})

        assert result is True


# ---------------------------------------------------------------------------
# ElasticSource
# ---------------------------------------------------------------------------


class TestElasticTestConnection:
    """Tests for ElasticSource.test_connection() — ES client info() call."""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        from parrot.tools.databasequery.sources.elastic import ElasticSource

        source = ElasticSource()
        es_client = AsyncMock()
        es_client.info = AsyncMock(return_value={"version": {"number": "8.0.0"}})

        conn_mock = MagicMock()
        conn_mock._connection = es_client

        mock_db = MagicMock()
        mock_db.connection = _make_async_context_manager(conn_mock)

        with patch.object(source, "_get_db", return_value=mock_db):
            result = await source.test_connection({"host": "es.host", "port": "9200"})

        assert result is True
        es_client.info.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_on_connection_failure(self) -> None:
        from parrot.tools.databasequery.sources.elastic import ElasticSource

        source = ElasticSource()
        with patch.object(source, "_get_db", side_effect=Exception("connection refused")):
            result = await source.test_connection({"host": "badhost"})

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_info_raises(self) -> None:
        from parrot.tools.databasequery.sources.elastic import ElasticSource

        source = ElasticSource()
        es_client = AsyncMock()
        es_client.info = AsyncMock(side_effect=Exception("unauthorized"))

        conn_mock = MagicMock()
        conn_mock._connection = es_client

        mock_db = MagicMock()
        mock_db.connection = _make_async_context_manager(conn_mock)

        with patch.object(source, "_get_db", return_value=mock_db):
            result = await source.test_connection({"host": "es.host"})

        assert result is False

    @pytest.mark.asyncio
    async def test_never_raises(self) -> None:
        from parrot.tools.databasequery.sources.elastic import ElasticSource

        source = ElasticSource()
        with patch.object(source, "_get_db", side_effect=RuntimeError("crash")):
            result = await source.test_connection({})

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_returns_bool_type(self) -> None:
        from parrot.tools.databasequery.sources.elastic import ElasticSource

        source = ElasticSource()
        with patch.object(source, "_get_db", side_effect=Exception("fail")):
            result = await source.test_connection({})

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_uses_dsn_when_provided(self) -> None:
        from parrot.tools.databasequery.sources.elastic import ElasticSource

        source = ElasticSource()
        es_client = AsyncMock()
        es_client.info = AsyncMock(return_value={})

        conn_mock = MagicMock()
        conn_mock._connection = es_client

        mock_db = MagicMock()
        mock_db.connection = _make_async_context_manager(conn_mock)

        with patch.object(source, "_get_db", return_value=mock_db) as mock_get_db:
            result = await source.test_connection({"dsn": "https://es.host:9200"})

        # Verify _get_db was called with dsn and no dsn in params
        call_args = mock_get_db.call_args
        assert call_args[0][1] == "https://es.host:9200"  # dsn
        assert result is True


# ---------------------------------------------------------------------------
# InfluxSource
# ---------------------------------------------------------------------------


class TestInfluxTestConnection:
    """Tests for InfluxSource.test_connection() — buckets() Flux query."""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        from parrot.tools.databasequery.sources.influx import InfluxSource

        source = InfluxSource()
        conn_mock = AsyncMock()
        conn_mock.query = AsyncMock(return_value=[{"name": "_monitoring"}])

        mock_db = MagicMock()
        mock_db.connection = _make_async_context_manager(conn_mock)

        with patch.object(source, "_get_db", return_value=mock_db):
            result = await source.test_connection({"token": "mytoken", "org": "myorg"})

        assert result is True
        conn_mock.query.assert_awaited_once_with("buckets()")

    @pytest.mark.asyncio
    async def test_returns_false_on_connection_failure(self) -> None:
        from parrot.tools.databasequery.sources.influx import InfluxSource

        source = InfluxSource()
        with patch.object(source, "_get_db", side_effect=Exception("connection refused")):
            result = await source.test_connection({"token": "badtoken"})

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_query_raises(self) -> None:
        from parrot.tools.databasequery.sources.influx import InfluxSource

        source = InfluxSource()
        conn_mock = AsyncMock()
        conn_mock.query = AsyncMock(side_effect=Exception("unauthorized"))

        mock_db = MagicMock()
        mock_db.connection = _make_async_context_manager(conn_mock)

        with patch.object(source, "_get_db", return_value=mock_db):
            result = await source.test_connection({"token": "mytoken"})

        assert result is False

    @pytest.mark.asyncio
    async def test_never_raises(self) -> None:
        from parrot.tools.databasequery.sources.influx import InfluxSource

        source = InfluxSource()
        with patch.object(source, "_get_db", side_effect=RuntimeError("crash")):
            result = await source.test_connection({})

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_returns_bool_type(self) -> None:
        from parrot.tools.databasequery.sources.influx import InfluxSource

        source = InfluxSource()
        with patch.object(source, "_get_db", side_effect=Exception("fail")):
            result = await source.test_connection({})

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_uses_dsn_when_provided(self) -> None:
        from parrot.tools.databasequery.sources.influx import InfluxSource

        source = InfluxSource()
        conn_mock = AsyncMock()
        conn_mock.query = AsyncMock(return_value=[])

        mock_db = MagicMock()
        mock_db.connection = _make_async_context_manager(conn_mock)

        with patch.object(source, "_get_db", return_value=mock_db) as mock_get_db:
            result = await source.test_connection({"dsn": "https://influx.host:8086"})

        call_args = mock_get_db.call_args
        assert call_args[0][1] == "https://influx.host:8086"  # dsn
        assert result is True
