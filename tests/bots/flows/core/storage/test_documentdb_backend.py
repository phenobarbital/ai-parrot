"""Unit tests for DocumentDbResultStorage backend."""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_documentdb(monkeypatch):
    """Patch DocumentDb with a recording mock."""
    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    instance.write = AsyncMock(return_value=None)
    instance.read = AsyncMock(return_value=[])
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.documentdb.DocumentDb",
        cls,
    )
    return instance


@pytest.mark.asyncio
async def test_documentdb_save_uses_async_with(mock_documentdb):
    """save() must open DocumentDb via async-with and call write() once."""
    from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

    backend = DocumentDbResultStorage()
    await backend.save("crew_executions", {"crew_name": "x"})

    mock_documentdb.__aenter__.assert_awaited_once()
    mock_documentdb.write.assert_awaited_once()
    # FEAT-307: save() now stamps a generated `record_id` onto the document
    # (find_documents() strips Mongo's own `_id`, so callers need a stable id).
    written_collection, written_doc = mock_documentdb.write.await_args.args
    assert written_collection == "crew_executions"
    assert written_doc["crew_name"] == "x"
    assert "record_id" in written_doc
    mock_documentdb.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_documentdb_close_is_noop():
    """close() returns None and does not raise even if save was never called."""
    from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

    backend = DocumentDbResultStorage()
    assert await backend.close() is None


@pytest.mark.asyncio
async def test_documentdb_each_save_opens_new_context(mock_documentdb):
    """Two calls to save() each open a fresh DocumentDb context."""
    from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

    backend = DocumentDbResultStorage()
    await backend.save("crew_executions", {"crew_name": "a"})
    await backend.save("crew_executions", {"crew_name": "b"})

    assert mock_documentdb.__aenter__.await_count == 2
    assert mock_documentdb.write.await_count == 2


@pytest.mark.asyncio
async def test_documentdb_fetch_filters_by_execution_id(mock_documentdb):
    """fetch() queries with {"execution_id": <value>} on the given collection."""
    from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

    mock_documentdb.read = AsyncMock(return_value=[{"execution_id": "E1"}])
    backend = DocumentDbResultStorage()
    docs = await backend.fetch("crew_agent_results", "E1")

    mock_documentdb.read.assert_awaited_once_with(
        "crew_agent_results", {"execution_id": "E1"}
    )
    assert docs == [{"execution_id": "E1"}]


@pytest.mark.asyncio
async def test_documentdb_fetch_reraises_on_error(mock_documentdb, caplog):
    """fetch() logs then re-raises on error (unlike save())."""
    from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage

    mock_documentdb.read = AsyncMock(side_effect=RuntimeError("db down"))
    backend = DocumentDbResultStorage()

    with pytest.raises(RuntimeError):
        await backend.fetch("crew_agent_results", "E1")
    assert "DocumentDbResultStorage fetch failed" in caplog.text
