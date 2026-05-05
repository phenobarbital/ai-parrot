"""Shared fixtures for FEAT-147 integration tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_documentdb(monkeypatch):
    """Patch DocumentDb with an in-memory async mock.

    Returns:
        Tuple of (cls_mock, instance_mock).
    """
    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    instance.write = AsyncMock(return_value=None)
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.documentdb.DocumentDb",
        cls,
    )
    return cls, instance


@pytest.fixture
def mock_asyncdb_pg(monkeypatch):
    """Patch AsyncDB (Postgres driver) with an async mock.

    Returns:
        Tuple of (cls_mock, connection_mock).
    """
    conn = MagicMock()
    conn.connection = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)
    cls = MagicMock(return_value=conn)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.postgres.AsyncDB",
        cls,
    )
    return cls, conn


@pytest.fixture
def mock_asyncdb_redis(monkeypatch):
    """Patch AsyncDB (Redis driver) with an async mock.

    Returns:
        Tuple of (cls_mock, connection_mock).
    """
    conn = MagicMock()
    conn.connection = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)
    cls = MagicMock(return_value=conn)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.redis.AsyncDB",
        cls,
    )
    return cls, conn
