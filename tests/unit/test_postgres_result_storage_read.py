"""Unit tests for PostgresResultStorage read methods (FEAT-307)."""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_asyncdb(monkeypatch):
    """Patch asyncdb.AsyncDB with a recording pg mock."""
    conn = MagicMock()
    conn.connection = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=0)
    conn.close = AsyncMock(return_value=None)
    cls = MagicMock(return_value=conn)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.postgres.AsyncDB",
        cls,
    )
    return conn


class TestPostgresResultStorageRead:
    @pytest.mark.asyncio
    async def test_list_with_filters(self, mock_asyncdb):
        """list() builds correct WHERE clause from filters."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetch.return_value = []
        backend = PostgresResultStorage(dsn="postgres://x/y")

        await backend.list(
            "crew_executions",
            filters={"tenant": "acme", "user_id": "u1", "crew_name": "research"},
        )

        query, *params = mock_asyncdb.fetch.await_args.args
        assert "COALESCE(tenant, 'global') = $1" in query
        assert "user_id = $2" in query
        assert "crew_name = $3" in query
        assert params[:3] == ["acme", "u1", "research"]

    @pytest.mark.asyncio
    async def test_list_pagination(self, mock_asyncdb):
        """list() respects limit and offset."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetch.return_value = []
        backend = PostgresResultStorage(dsn="postgres://x/y")

        await backend.list("crew_executions", limit=5, offset=10)

        query, *params = mock_asyncdb.fetch.await_args.args
        assert "LIMIT $1 OFFSET $2" in query
        assert params == [5, 10]

    @pytest.mark.asyncio
    async def test_list_empty_result(self, mock_asyncdb):
        """list() returns empty list when no matches."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetch.return_value = []
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.list("crew_executions")

        assert result == []

    @pytest.mark.asyncio
    async def test_list_parses_payload(self, mock_asyncdb):
        """list() parses the payload jsonb column into a dict."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetch.return_value = [
            {
                "id": "abc-123",
                "crew_name": "research",
                "method": "run_flow",
                "user_id": "u1",
                "session_id": None,
                "timestamp": "2026-01-01T00:00:00",
                "tenant": "acme",
                "prompt": "Analyze trends",
                "payload": json.dumps({"result": {"raw": "ok"}}),
            }
        ]
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.list("crew_executions")

        assert result[0]["id"] == "abc-123"
        assert result[0]["payload"] == {"result": {"raw": "ok"}}

    @pytest.mark.asyncio
    async def test_get_by_id(self, mock_asyncdb):
        """get() returns record matching UUID."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetchrow.return_value = {
            "id": "abc-123",
            "crew_name": "research",
            "method": "run_flow",
            "payload": {"result": "ok"},
        }
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.get("crew_executions", "abc-123")

        assert result["id"] == "abc-123"
        query, record_id = mock_asyncdb.fetchrow.await_args.args
        assert "WHERE id = $1" in query
        assert record_id == "abc-123"

    @pytest.mark.asyncio
    async def test_get_not_found(self, mock_asyncdb):
        """get() returns None when UUID not found."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetchrow.return_value = None
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.get("crew_executions", "missing-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_asyncdb):
        """delete() removes record and returns True."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.execute.return_value = "DELETE 1"
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.delete("crew_executions", "abc-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mock_asyncdb):
        """delete() returns False when UUID not found."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.execute.return_value = "DELETE 0"
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.delete("crew_executions", "missing-id")

        assert result is False

    @pytest.mark.asyncio
    async def test_count_with_filters(self, mock_asyncdb):
        """count() returns correct total with filters."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetchval.return_value = 3
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.count("crew_executions", filters={"tenant": "acme"})

        assert result == 3
        query, *params = mock_asyncdb.fetchval.await_args.args
        assert "COALESCE(tenant, 'global') = $1" in query
        assert params == ["acme"]

    @pytest.mark.asyncio
    async def test_tenant_coalesce(self, mock_asyncdb):
        """Queries use COALESCE(tenant, 'global') for legacy rows."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetch.return_value = []
        backend = PostgresResultStorage(dsn="postgres://x/y")

        await backend.list("crew_executions", filters={"tenant": "global"})

        query, *_ = mock_asyncdb.fetch.await_args.args
        assert "COALESCE(tenant, 'global')" in query

    @pytest.mark.asyncio
    async def test_list_swallows_exceptions(self, mock_asyncdb, caplog):
        """list() logs a warning and returns [] on backend failure."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetch.side_effect = RuntimeError("pg down")
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.list("crew_executions")

        assert result == []
        assert "PostgresResultStorage list failed" in caplog.text

    @pytest.mark.asyncio
    async def test_get_swallows_exceptions(self, mock_asyncdb, caplog):
        """get() logs a warning and returns None on backend failure."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetchrow.side_effect = RuntimeError("pg down")
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.get("crew_executions", "abc-123")

        assert result is None
        assert "PostgresResultStorage get failed" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_swallows_exceptions(self, mock_asyncdb, caplog):
        """delete() logs a warning and returns False on backend failure."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.execute.side_effect = RuntimeError("pg down")
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.delete("crew_executions", "abc-123")

        assert result is False
        assert "PostgresResultStorage delete failed" in caplog.text

    @pytest.mark.asyncio
    async def test_count_swallows_exceptions(self, mock_asyncdb, caplog):
        """count() logs a warning and returns 0 on backend failure."""
        from parrot.bots.flows.core.storage.backends import PostgresResultStorage

        mock_asyncdb.fetchval.side_effect = RuntimeError("pg down")
        backend = PostgresResultStorage(dsn="postgres://x/y")

        result = await backend.count("crew_executions")

        assert result == 0
        assert "PostgresResultStorage count failed" in caplog.text
