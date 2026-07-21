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
    # payload is the last positional arg. Column order:
    # crew_name, method, user_id, session_id, execution_id, timestamp,
    # tenant, prompt, payload — args[0] is the query string, so payload
    # (the 9th column) lands at args[9]. Shifted twice: once by FEAT-306's
    # execution_id column, once by FEAT-307's tenant/prompt columns.
    payload_arg = insert_call.args[9]
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


@pytest.mark.asyncio
async def test_postgres_ddl_includes_execution_id(mock_asyncdb):
    """DDL includes the execution_id column, its ALTER, and its index."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.save("crew_executions", {"crew_name": "x", "method": "m"})

    calls = [c.args[0] for c in mock_asyncdb.execute.await_args_list]
    assert any(
        "CREATE TABLE IF NOT EXISTS crew_executions" in q and "execution_id" in q
        for q in calls
    )
    assert any(
        "ALTER TABLE crew_executions ADD COLUMN IF NOT EXISTS execution_id" in q
        for q in calls
    )
    assert any("crew_executions_execution_id_idx" in q for q in calls)


@pytest.mark.asyncio
async def test_postgres_save_extracts_execution_id_to_column(mock_asyncdb):
    """save() routes execution_id to its own positional column, not payload."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.save(
        "crew_executions",
        {"crew_name": "x", "method": "m", "execution_id": "E1"},
    )

    insert_call = next(
        c
        for c in mock_asyncdb.execute.await_args_list
        if "INSERT INTO" in c.args[0]
    )
    assert insert_call.args[5] == "E1"  # execution_id positional column
    # payload is now at args[9] — shifted by FEAT-307's tenant/prompt columns
    # (inserted between execution_id/timestamp and payload). See the merge
    # note on test_postgres_wraps_bare_string_result above.
    payload = json.loads(insert_call.args[9])
    assert "execution_id" not in payload


@pytest.mark.asyncio
async def test_postgres_fetch_selects_by_execution_id(mock_asyncdb):
    """fetch() selects rows by execution_id and merges payload with columns."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    mock_asyncdb.execute.return_value = [
        {
            "crew_name": "x",
            "method": "m",
            "user_id": None,
            "session_id": None,
            "execution_id": "E1",
            "timestamp": "2026-07-14T00:00:00+00:00",
            "payload": json.dumps({"output": "ok"}),
        }
    ]
    backend = PostgresResultStorage(dsn="postgres://x/y")
    docs = await backend.fetch("crew_executions", "E1")

    assert len(docs) == 1
    assert docs[0]["execution_id"] == "E1"
    assert docs[0]["output"] == "ok"
    select_call = next(
        c for c in mock_asyncdb.execute.await_args_list if "SELECT" in c.args[0]
    )
    assert "WHERE execution_id = $1" in select_call.args[0]
    assert select_call.args[1] == "E1"


@pytest.mark.asyncio
async def test_postgres_fetch_returns_empty_on_no_match(mock_asyncdb):
    """fetch() returns [] when no rows match."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    mock_asyncdb.execute.return_value = []
    backend = PostgresResultStorage(dsn="postgres://x/y")
    docs = await backend.fetch("crew_executions", "unknown")
    assert docs == []


@pytest.mark.asyncio
async def test_postgres_fetch_reraises_on_error(mock_asyncdb, caplog):
    """fetch() logs then re-raises on connection/query errors (unlike save())."""
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage

    mock_asyncdb.execute.side_effect = RuntimeError("pg down")
    backend = PostgresResultStorage(dsn="postgres://x/y")

    with pytest.raises(RuntimeError):
        await backend.fetch("crew_executions", "E1")
    assert "PostgresResultStorage fetch failed" in caplog.text
