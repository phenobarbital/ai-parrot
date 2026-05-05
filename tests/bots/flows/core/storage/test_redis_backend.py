"""Unit tests for RedisResultStorage backend."""
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
    return conn, cls


@pytest.mark.asyncio
async def test_redis_save_uses_ttl_by_default(mock_asyncdb):
    """save() with ttl>0 passes EX <ttl> to the SET command."""
    from parrot.bots.flows.core.storage.backends import RedisResultStorage

    conn, _ = mock_asyncdb
    backend = RedisResultStorage(ttl=60)
    await backend.save("crew_executions", {"crew_name": "x"})

    args = conn.execute.await_args.args
    assert args[0] == "SET"
    assert args[1].startswith("crew_executions:x:")
    assert "EX" in args
    assert args[args.index("EX") + 1] == "60"


@pytest.mark.asyncio
async def test_redis_save_omits_ttl_when_zero(mock_asyncdb):
    """save() with ttl=0 omits EX argument entirely."""
    from parrot.bots.flows.core.storage.backends import RedisResultStorage

    conn, _ = mock_asyncdb
    backend = RedisResultStorage(ttl=0)
    await backend.save("crew_executions", {"crew_name": "x"})

    args = conn.execute.await_args.args
    assert "EX" not in args


@pytest.mark.asyncio
async def test_redis_save_swallows_exceptions(mock_asyncdb, caplog):
    """save() logs a warning and does not propagate on backend failure."""
    from parrot.bots.flows.core.storage.backends import RedisResultStorage

    conn, _ = mock_asyncdb
    conn.execute.side_effect = RuntimeError("redis down")
    backend = RedisResultStorage(ttl=60)

    # Should not raise
    await backend.save("crew_executions", {"crew_name": "x"})

    assert "RedisResultStorage save failed" in caplog.text


@pytest.mark.asyncio
async def test_redis_close_idempotent(mock_asyncdb):
    """close() is safe to call multiple times, including before any save."""
    from parrot.bots.flows.core.storage.backends import RedisResultStorage

    conn, _ = mock_asyncdb
    backend = RedisResultStorage(ttl=60)

    await backend.close()  # never connected → no-op
    await backend.save("crew_executions", {"crew_name": "x"})
    await backend.close()
    await backend.close()  # second close → no-op

    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_lazy_connect(mock_asyncdb):
    """First save() creates one AsyncDB; second reuses the same connection."""
    from parrot.bots.flows.core.storage.backends import RedisResultStorage

    conn, cls = mock_asyncdb
    backend = RedisResultStorage(ttl=60)

    await backend.save("crew_executions", {"crew_name": "a"})
    await backend.save("crew_executions", {"crew_name": "b"})

    cls.assert_called_once()  # only one constructor call
    conn.connection.assert_awaited_once()  # only one open


@pytest.mark.asyncio
async def test_redis_value_is_valid_json(mock_asyncdb):
    """The value written to Redis is valid JSON."""
    from parrot.bots.flows.core.storage.backends import RedisResultStorage

    conn, _ = mock_asyncdb
    backend = RedisResultStorage(ttl=0)
    doc = {"crew_name": "x", "method": "run_flow", "result": "some string"}
    await backend.save("crew_executions", doc)

    args = conn.execute.await_args.args
    # The value is the second positional arg (after SET <key>)
    value_json = args[2]
    parsed = json.loads(value_json)
    assert parsed["method"] == "run_flow"
