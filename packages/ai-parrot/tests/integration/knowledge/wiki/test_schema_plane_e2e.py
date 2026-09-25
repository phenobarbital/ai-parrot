"""FEAT-600 end-to-end schema-plane integration scenarios."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.bots.database.toolkits.sql import SQLToolkit
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig, SchemaSourceConfig
from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.knowledge.wiki.schema.tools import create_schema_tools

DDL_CORPUS = Path("packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql")


class _SQLiteIntegrationToolkit(SQLToolkit):
    """SQL toolkit that introspects the real SQLite file used by this test."""

    async def describe_table(self, schema: str, table: str) -> TableMetadata | None:
        """Build full metadata from SQLite's table and foreign-key pragmas."""

        def read_metadata() -> TableMetadata | None:
            with sqlite3.connect(self.dsn) as connection:
                pragma_table = table.replace("'", "''")
                columns = connection.execute(f"PRAGMA {schema}.table_info('{pragma_table}')").fetchall()
                if not columns:
                    return None
                foreign_keys = connection.execute(f"PRAGMA {schema}.foreign_key_list('{pragma_table}')").fetchall()

            foreign_key_by_column = {row[3]: row for row in foreign_keys}
            return TableMetadata(
                schema=schema,
                tablename=table,
                table_type="BASE TABLE",
                full_name=f'"{schema}"."{table}"',
                columns=[
                    {
                        "name": row[1],
                        "type": row[2] or "unknown",
                        "nullable": not bool(row[3]),
                        "default": row[4],
                    }
                    for row in columns
                ],
                primary_keys=[row[1] for row in columns if row[5]],
                foreign_keys=[
                    {
                        "column": row[3],
                        "ref_schema": schema,
                        "ref_table": row[2],
                        "ref_column": row[4],
                    }
                    for row in foreign_key_by_column.values()
                ],
                completeness=Completeness.FULL,
                source="information_schema",
            )

        return await asyncio.to_thread(read_metadata)


@pytest.fixture
def svc(tmp_path: Path) -> SchemaPlaneService:
    """Create a writable throwaway schema plane."""

    return SchemaPlaneService.from_dir(tmp_path / "schema", config=SchemaPlaneConfig(), read_only=False)


async def test_ddl_ingest_then_tool_lookup(svc: SchemaPlaneService) -> None:
    """DDL ingest creates six pages and exposes their DDL through schema tools."""

    report = await svc.ingest_ddl([DDL_CORPUS], origin="taskmem", dialect="postgres", root=Path("."))
    assert len(report.created) == 6
    assert not report.parse_errors

    tools = {tool.name: tool for tool in create_schema_tools(svc.store, None, WikiProjectConfig(), service=svc)}
    result = await tools["wiki_schema_lookup"]._execute(ref=report.created[0].replace("table:taskmem/", "taskmem:"))

    assert result.success
    assert result.result["ddl"].startswith("CREATE TABLE")
    assert any(relation["rel"] == "defined_in" for relation in result.result["relations"])


async def test_live_sqlite_sync_and_plane_warmed_partition(tmp_path: Path, svc: SchemaPlaneService) -> None:
    """Sync SQLite metadata, traverse its FK, then read it after DB removal."""

    db = tmp_path / "live.db"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            "CREATE TABLE stores(id INTEGER PRIMARY KEY); "
            "CREATE TABLE sales(id INTEGER PRIMARY KEY, store_id INTEGER REFERENCES stores(id));"
        )

    svc.config.sources["sqlite"] = SchemaSourceConfig(
        alias="sqlite",
        dialect="sqlite",
        dsn_env="LIVE_DSN",
        allowed_schemas=["main"],
        tables=["main.stores", "main.sales"],
    )
    toolkit = _SQLiteIntegrationToolkit(
        dsn=str(db),
        allowed_schemas=["main"],
        primary_schema="main",
        tables=["main.stores", "main.sales"],
        database_type="sqlite",
    )
    report = await svc.sync("sqlite", dsn_resolver=lambda _name: str(db), toolkit=toolkit)

    assert set(report.created) == {"table:sqlite/main.stores", "table:sqlite/main.sales"}
    hops = await svc.neighbors("sqlite:main.sales", depth=1)
    assert hops and hops[0]["target"] == "table:sqlite/main.stores"

    db.unlink()
    from parrot.bots.database.cache import CachePartition

    partition = CachePartition(namespace="sqlite_main", plane=svc, origin="sqlite")
    metadata = await partition.get("main", "sales")
    assert metadata is not None
    assert metadata.tablename == "sales"


@pytest.mark.skipif(
    os.environ.get("PARROT_TEST_SCHEMA_PLANE") != "1",
    reason="opt-in: runs the bots/database suite with the plane on",
)
def test_bots_database_suite_with_plane_on() -> None:
    """Run the existing database suite with the schema-plane toggle enabled."""

    env = {**os.environ, "PARROT_TEST_SCHEMA_PLANE": "1"}
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "packages/ai-parrot/tests/bots/database", "-q"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stdout[-2000:]
