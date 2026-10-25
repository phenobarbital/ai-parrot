"""Regression contract: Repair stock DuckDB source execution (M9D)."""

from __future__ import annotations

import asyncio
import builtins
import importlib
import time
from pathlib import Path
from typing import Any

import duckdb
import pytest

from parrot.tools.databasequery.sources import duckdb as duckdb_source_module
from parrot.tools.databasequery.sources.duckdb import DuckDBSource


def _create_warehouse(path: Path) -> dict[str, str]:
    """Create a deterministic file-backed DuckDB warehouse."""
    connection = duckdb.connect(str(path))
    try:
        connection.execute("CREATE TABLE orders (id INTEGER, region VARCHAR, amount DOUBLE)")
        connection.execute(
            "INSERT INTO orders VALUES "
            "(1, 'EU', 10.0), (2, 'US', 20.0), (3, 'EU', 30.0)"
        )
    finally:
        connection.close()
    return {"database": str(path)}


@pytest.mark.asyncio
async def test_real_file_queries_params_and_empty_columns(tmp_path: Path) -> None:
    """Verify real file queries params and empty columns."""
    credentials = await asyncio.to_thread(_create_warehouse, tmp_path / "warehouse.duckdb")
    source = DuckDBSource()

    named = await source.query(
        credentials,
        "SELECT id FROM orders WHERE region = $region ORDER BY id",
        {"region": "EU"},
    )
    positional = await source.query(
        credentials,
        "SELECT id FROM orders WHERE amount > ? ORDER BY id",
        [15.0],  # type: ignore[arg-type] -- positional parameters are part of the preserved runtime API.
    )
    empty = await source.query(credentials, "SELECT id, region FROM orders WHERE FALSE")
    row = await source.query_row(credentials, "SELECT id, region FROM orders WHERE id = 2")
    missing = await source.query_row(credentials, "SELECT id FROM orders WHERE id = 99")

    assert named.rows == [{"id": 1}, {"id": 3}]
    assert positional.rows == [{"id": 2}, {"id": 3}]
    assert empty.rows == []
    assert empty.row_count == 0
    assert empty.columns == ["id", "region"]
    assert row.found is True
    assert row.row == {"id": 2, "region": "US"}
    assert missing.found is False
    assert missing.row is None


@pytest.mark.asyncio
async def test_metadata_validation_and_connection_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify metadata validation and connection cleanup."""
    credentials = await asyncio.to_thread(_create_warehouse, tmp_path / "warehouse.duckdb")
    real_connect = duckdb.connect

    class TrackingConnection:
        """Proxy a real DuckDB connection while recording closure."""

        def __init__(self, connection: Any) -> None:
            self.connection = connection
            self.closed = False

        def execute(self, sql: str, params: Any = None) -> Any:
            """Execute SQL through the real connection."""
            if params is None:
                return self.connection.execute(sql)
            return self.connection.execute(sql, params)

        def close(self) -> None:
            """Close the real connection and record cleanup."""
            self.connection.close()
            self.closed = True

    opened_connections: list[TrackingConnection] = []

    def tracking_connect(*args: Any, **kwargs: Any) -> TrackingConnection:
        """Create a tracked real DuckDB connection."""
        connection = TrackingConnection(real_connect(*args, **kwargs))
        opened_connections.append(connection)
        return connection

    monkeypatch.setattr(duckdb, "connect", tracking_connect)
    source = DuckDBSource()

    metadata = await source.get_metadata(credentials, ["orders"])
    assert [table.name for table in metadata.tables] == ["orders"]
    assert [column.name for column in metadata.tables[0].columns] == ["id", "region", "amount"]
    assert len(opened_connections) == 1
    assert opened_connections[0].closed is True

    with pytest.raises(ValueError, match="Invalid SQL table name"):
        await source.get_metadata(credentials, ["orders'; DROP TABLE orders; --"])
    assert len(opened_connections) == 1

    with pytest.raises(duckdb.Error):
        await source.query(credentials, "SELECT * FROM missing_table")
    assert len(opened_connections) == 2
    assert opened_connections[1].closed is True


@pytest.mark.asyncio
async def test_event_loop_responsiveness_and_lazy_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify event loop responsiveness and lazy import."""
    real_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        """Reject an import-time DuckDB dependency."""
        if name == "duckdb":
            raise ModuleNotFoundError("No module named 'duckdb'", name="duckdb")
        return real_import(name, *args, **kwargs)

    with monkeypatch.context() as import_context:
        import_context.setattr(builtins, "__import__", guarded_import)
        importlib.reload(duckdb_source_module)
        with pytest.raises(ImportError, match="DuckDB support.*'duckdb' extra"):
            await duckdb_source_module.DuckDBSource().query({}, "SELECT 1")

    credentials = await asyncio.to_thread(_create_warehouse, tmp_path / "warehouse.duckdb")
    source = duckdb_source_module.DuckDBSource()
    execute_sync = source._execute_sync

    def delayed_execute(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], list[str]]:
        """Add deterministic blocking work before a real DuckDB query."""
        time.sleep(0.25)
        return execute_sync(*args, **kwargs)

    monkeypatch.setattr(source, "_execute_sync", delayed_execute)
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    query_task = asyncio.create_task(source.query(credentials, "SELECT COUNT(*) AS count FROM orders"))
    await asyncio.sleep(0.02)
    heartbeat_elapsed = loop.time() - started_at
    result = await query_task

    assert heartbeat_elapsed < 0.15
    assert result.rows == [{"count": 3}]
