"""Unit tests for RedisResultStorage read methods (FEAT-307)."""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_asyncdb(monkeypatch):
    """Patch asyncdb.AsyncDB with a recording redis mock."""
    conn = MagicMock()
    conn.connection = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)
    cls = MagicMock(return_value=conn)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.redis.AsyncDB",
        cls,
    )
    return conn


def _scan_and_mget(conn, keys_by_cursor, values_by_key):
    """Configure conn.execute to answer SCAN/MGET/GET/DEL calls from fixtures."""

    async def _execute(cmd, *args):
        if cmd == "SCAN":
            cursor = args[0]
            keys = keys_by_cursor.get(cursor, [])
            next_cursor = "0"
            return [next_cursor, keys]
        if cmd == "MGET":
            return [values_by_key.get(k) for k in args]
        if cmd == "GET":
            return values_by_key.get(args[0])
        if cmd == "DEL":
            return 1 if args[0] in values_by_key else 0
        return None

    conn.execute.side_effect = _execute


class TestRedisResultStorageRead:
    @pytest.mark.asyncio
    async def test_list_scans_and_filters(self, mock_asyncdb):
        """list() uses SCAN + MGET and filters by tenant/user_id."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        doc_a = {"crew_name": "a", "user_id": "u1", "tenant": "acme", "timestamp": 1.0}
        doc_b = {"crew_name": "b", "user_id": "u2", "tenant": "other", "timestamp": 2.0}
        keys_by_cursor = {"0": ["crew_executions:a:1", "crew_executions:b:2"]}
        values_by_key = {
            "crew_executions:a:1": json.dumps(doc_a),
            "crew_executions:b:2": json.dumps(doc_b),
        }
        _scan_and_mget(mock_asyncdb, keys_by_cursor, values_by_key)

        backend = RedisResultStorage(ttl=0)
        result = await backend.list("crew_executions", filters={"tenant": "acme"})

        assert len(result) == 1
        assert result[0]["crew_name"] == "a"
        assert result[0]["id"] == "crew_executions:a:1"

    @pytest.mark.asyncio
    async def test_list_pagination(self, mock_asyncdb):
        """list() applies offset and limit after filtering."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        docs = {
            f"crew_executions:x:{i}": json.dumps({"crew_name": "x", "timestamp": float(i)})
            for i in range(5)
        }
        keys_by_cursor = {"0": list(docs.keys())}
        _scan_and_mget(mock_asyncdb, keys_by_cursor, docs)

        backend = RedisResultStorage(ttl=0)
        result = await backend.list("crew_executions", limit=2, offset=1)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_sort_by_timestamp(self, mock_asyncdb):
        """list() returns results newest first."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        doc_old = {"crew_name": "x", "timestamp": 1.0}
        doc_new = {"crew_name": "x", "timestamp": 2.0}
        keys_by_cursor = {"0": ["crew_executions:x:1", "crew_executions:x:2"]}
        values_by_key = {
            "crew_executions:x:1": json.dumps(doc_old),
            "crew_executions:x:2": json.dumps(doc_new),
        }
        _scan_and_mget(mock_asyncdb, keys_by_cursor, values_by_key)

        backend = RedisResultStorage(ttl=0)
        result = await backend.list("crew_executions")

        assert result[0]["timestamp"] == 2.0
        assert result[1]["timestamp"] == 1.0

    @pytest.mark.asyncio
    async def test_get_by_key(self, mock_asyncdb):
        """get() finds document by key identifier."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        doc = {"crew_name": "x", "timestamp": 1.0}
        values_by_key = {"crew_executions:x:1": json.dumps(doc)}
        _scan_and_mget(mock_asyncdb, {}, values_by_key)

        backend = RedisResultStorage(ttl=0)
        result = await backend.get("crew_executions", "crew_executions:x:1")

        assert result["crew_name"] == "x"
        assert result["id"] == "crew_executions:x:1"

    @pytest.mark.asyncio
    async def test_get_not_found(self, mock_asyncdb):
        """get() returns None when key not found."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        _scan_and_mget(mock_asyncdb, {}, {})

        backend = RedisResultStorage(ttl=0)
        # Prefixed with the collection so this exercises the "no value in
        # Redis" path, not the collection-ownership check below.
        result = await backend.get("crew_executions", "crew_executions:missing:999")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_rejects_key_outside_collection(self, mock_asyncdb):
        """get() refuses a record_id that doesn't belong to the given collection.

        Security regression test: without this check, a caller could pass an
        arbitrary Redis key (e.g. from a different collection, or an
        unrelated cache/session key) and read it back through this backend.
        """
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        backend = RedisResultStorage(ttl=0)
        result = await backend.get("crew_executions", "some_other_collection:x:1")

        assert result is None
        mock_asyncdb.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_asyncdb):
        """delete() removes key and returns True."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        _scan_and_mget(mock_asyncdb, {}, {"crew_executions:x:1": json.dumps({})})

        backend = RedisResultStorage(ttl=0)
        result = await backend.delete("crew_executions", "crew_executions:x:1")

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mock_asyncdb):
        """delete() returns False when key not found."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        _scan_and_mget(mock_asyncdb, {}, {})

        backend = RedisResultStorage(ttl=0)
        result = await backend.delete("crew_executions", "crew_executions:missing:999")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_rejects_key_outside_collection(self, mock_asyncdb):
        """delete() refuses a record_id that doesn't belong to the given collection."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        backend = RedisResultStorage(ttl=0)
        result = await backend.delete("crew_executions", "some_other_collection:x:1")

        assert result is False
        mock_asyncdb.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_count_matches_filter(self, mock_asyncdb):
        """count() returns correct count after filtering."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        doc_a = {"crew_name": "a", "tenant": "acme", "timestamp": 1.0}
        doc_b = {"crew_name": "b", "tenant": "other", "timestamp": 2.0}
        keys_by_cursor = {"0": ["crew_executions:a:1", "crew_executions:b:2"]}
        values_by_key = {
            "crew_executions:a:1": json.dumps(doc_a),
            "crew_executions:b:2": json.dumps(doc_b),
        }
        _scan_and_mget(mock_asyncdb, keys_by_cursor, values_by_key)

        backend = RedisResultStorage(ttl=0)
        result = await backend.count("crew_executions", filters={"tenant": "acme"})

        assert result == 1

    @pytest.mark.asyncio
    async def test_list_swallows_exceptions(self, mock_asyncdb, caplog):
        """list() logs a warning and returns [] on backend failure."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        mock_asyncdb.execute.side_effect = RuntimeError("redis down")
        backend = RedisResultStorage(ttl=0)

        result = await backend.list("crew_executions")

        assert result == []
        assert "RedisResultStorage list failed" in caplog.text

    @pytest.mark.asyncio
    async def test_get_swallows_exceptions(self, mock_asyncdb, caplog):
        """get() logs a warning and returns None on backend failure."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        mock_asyncdb.execute.side_effect = RuntimeError("redis down")
        backend = RedisResultStorage(ttl=0)

        result = await backend.get("crew_executions", "crew_executions:some-key")

        assert result is None
        assert "RedisResultStorage get failed" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_swallows_exceptions(self, mock_asyncdb, caplog):
        """delete() logs a warning and returns False on backend failure."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        mock_asyncdb.execute.side_effect = RuntimeError("redis down")
        backend = RedisResultStorage(ttl=0)

        result = await backend.delete("crew_executions", "crew_executions:some-key")

        assert result is False
        assert "RedisResultStorage delete failed" in caplog.text

    @pytest.mark.asyncio
    async def test_count_swallows_exceptions(self, mock_asyncdb, caplog):
        """count() logs a warning and returns 0 on backend failure."""
        from parrot.bots.flows.core.storage.backends import RedisResultStorage

        mock_asyncdb.execute.side_effect = RuntimeError("redis down")
        backend = RedisResultStorage(ttl=0)

        result = await backend.count("crew_executions")

        assert result == 0
        assert "RedisResultStorage count failed" in caplog.text
