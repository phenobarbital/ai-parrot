"""Unit tests for DocumentDbResultStorage read methods (FEAT-307)."""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_documentdb(monkeypatch):
    """Patch DocumentDb with a recording mock."""
    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    instance.write = AsyncMock(return_value=None)
    instance.find_documents = AsyncMock(return_value=[])
    instance.read_one = AsyncMock(return_value=None)
    instance.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.documentdb.DocumentDb",
        cls,
    )
    return instance


class TestDocumentDbResultStorageRead:
    @pytest.mark.asyncio
    async def test_list_builds_query(self, mock_documentdb):
        """list() builds correct MongoDB query from filters."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        backend = DocumentDbResultStorage()
        await backend.list(
            "crew_executions",
            filters={"tenant": "acme", "user_id": "u1", "crew_name": "research"},
        )

        _, query = mock_documentdb.find_documents.await_args.args
        assert query == {
            "tenant": "acme",
            "user_id": "u1",
            "crew_name": "research",
        }

    @pytest.mark.asyncio
    async def test_list_sorts_by_timestamp(self, mock_documentdb):
        """list() requests sort by timestamp descending."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        backend = DocumentDbResultStorage()
        await backend.list("crew_executions")

        kwargs = mock_documentdb.find_documents.await_args.kwargs
        assert kwargs["sort"] == [("timestamp", -1)]

    @pytest.mark.asyncio
    async def test_list_pagination(self, mock_documentdb):
        """list() applies offset and limit."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        mock_documentdb.find_documents.return_value = [
            {"crew_name": f"x{i}"} for i in range(5)
        ]
        backend = DocumentDbResultStorage()

        result = await backend.list("crew_executions", limit=2, offset=1)

        kwargs = mock_documentdb.find_documents.await_args.kwargs
        assert kwargs["limit"] == 3  # limit + offset
        assert len(result) == 2
        assert result[0]["crew_name"] == "x1"

    @pytest.mark.asyncio
    async def test_get_by_record_id(self, mock_documentdb):
        """get() finds document by record_id."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        mock_documentdb.read_one.return_value = {
            "record_id": "abc-123",
            "crew_name": "research",
        }
        backend = DocumentDbResultStorage()

        result = await backend.get("crew_executions", "abc-123")

        assert result["crew_name"] == "research"
        _, query = mock_documentdb.read_one.await_args.args
        assert query == {"record_id": "abc-123"}

    @pytest.mark.asyncio
    async def test_get_not_found(self, mock_documentdb):
        """get() returns None when not found."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        mock_documentdb.read_one.return_value = None
        backend = DocumentDbResultStorage()

        result = await backend.get("crew_executions", "missing-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_documentdb):
        """delete() calls delete_many and returns True."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        mock_documentdb.delete_many.return_value = MagicMock(deleted_count=1)
        backend = DocumentDbResultStorage()

        result = await backend.delete("crew_executions", "abc-123")

        assert result is True
        _, query = mock_documentdb.delete_many.await_args.args
        assert query == {"record_id": "abc-123"}

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mock_documentdb):
        """delete() returns False when no document deleted."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        mock_documentdb.delete_many.return_value = MagicMock(deleted_count=0)
        backend = DocumentDbResultStorage()

        result = await backend.delete("crew_executions", "missing-id")

        assert result is False

    @pytest.mark.asyncio
    async def test_count(self, mock_documentdb):
        """count() returns correct total."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        mock_documentdb.find_documents.return_value = [
            {"crew_name": "a"}, {"crew_name": "b"}, {"crew_name": "c"},
        ]
        backend = DocumentDbResultStorage()

        result = await backend.count("crew_executions", filters={"tenant": "acme"})

        assert result == 3

    @pytest.mark.asyncio
    async def test_list_swallows_exceptions(self, mock_documentdb, caplog):
        """list() logs a warning and returns [] on backend failure."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        mock_documentdb.find_documents.side_effect = RuntimeError("mongo down")
        backend = DocumentDbResultStorage()

        result = await backend.list("crew_executions")

        assert result == []
        assert "DocumentDbResultStorage list failed" in caplog.text

    @pytest.mark.asyncio
    async def test_get_swallows_exceptions(self, mock_documentdb, caplog):
        """get() logs a warning and returns None on backend failure."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        mock_documentdb.read_one.side_effect = RuntimeError("mongo down")
        backend = DocumentDbResultStorage()

        result = await backend.get("crew_executions", "abc-123")

        assert result is None
        assert "DocumentDbResultStorage get failed" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_swallows_exceptions(self, mock_documentdb, caplog):
        """delete() logs a warning and returns False on backend failure."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        mock_documentdb.delete_many.side_effect = RuntimeError("mongo down")
        backend = DocumentDbResultStorage()

        result = await backend.delete("crew_executions", "abc-123")

        assert result is False
        assert "DocumentDbResultStorage delete failed" in caplog.text

    @pytest.mark.asyncio
    async def test_count_swallows_exceptions(self, mock_documentdb, caplog):
        """count() logs a warning and returns 0 on backend failure."""
        from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

        mock_documentdb.find_documents.side_effect = RuntimeError("mongo down")
        backend = DocumentDbResultStorage()

        result = await backend.count("crew_executions")

        assert result == 0
        assert "DocumentDbResultStorage count failed" in caplog.text
