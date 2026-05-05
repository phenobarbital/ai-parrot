"""Unit tests for PostgresResultStorage backend."""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_asyncdb(monkeypatch):
    """Patch asyncdb.AsyncDB with a recording pg mock."""
    conn = MagicMock()
    conn.connection = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)
    cls = MagicMock(return_value=conn)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.postgres.AsyncDB",
        cls,
    )
    return conn


@pytest.mark.asyncio
async def test_postgres_first_save_issues_ddl_and_insert(mock_asyncdb):
    """First save() for a table issues CREATE TABLE IF NOT EXISTS + INSERT."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.save("crew_executions", {"crew_name": "x", "method": "run_flow"})

    calls = [c.args[0] for c in mock_asyncdb.execute.await_args_list]
    assert any("CREATE TABLE IF NOT EXISTS crew_executions" in q for q in calls)
    assert any("INSERT INTO crew_executions" in q for q in calls)


@pytest.mark.asyncio
async def test_postgres_second_save_skips_ddl(mock_asyncdb):
    """Second save() for the same table skips the DDL (in-process cache)."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.save("crew_executions", {"crew_name": "x", "method": "m"})

    mock_asyncdb.execute.reset_mock()

    await backend.save("crew_executions", {"crew_name": "y", "method": "m"})
    calls = [c.args[0] for c in mock_asyncdb.execute.await_args_list]

    assert all("CREATE TABLE" not in q for q in calls)
    assert any("INSERT INTO crew_executions" in q for q in calls)


@pytest.mark.asyncio
async def test_postgres_rejects_unsafe_table_name(mock_asyncdb):
    """Unsafe table name is rejected before any SQL is issued."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    backend = PostgresResultStorage(dsn="postgres://x/y")
    # This should be swallowed by outer try/except — no DROP TABLE should reach SQL
    await backend.save("crew_executions; DROP TABLE x;", {"crew_name": "x"})

    calls = [c.args[0] for c in mock_asyncdb.execute.await_args_list]
    assert all("DROP TABLE" not in q for q in calls)


@pytest.mark.asyncio
async def test_postgres_wraps_bare_string_result(mock_asyncdb):
    """A bare-string result is wrapped as {"raw": ...} in the payload jsonb."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.save(
        "crew_executions",
        {"crew_name": "x", "method": "m", "result": "raw-string"},
    )

    insert_call = next(
        c
        for c in mock_asyncdb.execute.await_args_list
        if "INSERT INTO" in c.args[0]
    )
    # payload is the 6th positional arg (index 6 = args[6])
    payload_arg = insert_call.args[6]
    payload = json.loads(payload_arg)
    assert payload["result"] == {"raw": "raw-string"}


@pytest.mark.asyncio
async def test_postgres_close_idempotent(mock_asyncdb):
    """close() is safe to call multiple times, including before any save."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.close()  # never connected → no-op
    await backend.save("crew_executions", {"crew_name": "x", "method": "m"})
    await backend.close()
    await backend.close()  # second close → no-op

    mock_asyncdb.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_postgres_save_swallows_exceptions(mock_asyncdb, caplog):
    """save() logs a warning and does not propagate on backend failure."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    mock_asyncdb.execute.side_effect = RuntimeError("pg down")
    backend = PostgresResultStorage(dsn="postgres://x/y")

    await backend.save("crew_executions", {"crew_name": "x", "method": "m"})

    assert "PostgresResultStorage save failed" in caplog.text


@pytest.mark.asyncio
async def test_postgres_different_tables_each_get_ddl(mock_asyncdb):
    """Two different tables each trigger their own DDL block."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.save("crew_executions", {"crew_name": "x", "method": "m"})
    await backend.save("flow_executions", {"crew_name": "x", "method": "m"})

    calls = [c.args[0] for c in mock_asyncdb.execute.await_args_list]
    assert any("CREATE TABLE IF NOT EXISTS crew_executions" in q for q in calls)
    assert any("CREATE TABLE IF NOT EXISTS flow_executions" in q for q in calls)
