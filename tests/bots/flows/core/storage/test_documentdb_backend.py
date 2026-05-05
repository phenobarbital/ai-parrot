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
    mock_documentdb.write.assert_awaited_once_with(
        "crew_executions", {"crew_name": "x"}
    )
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
