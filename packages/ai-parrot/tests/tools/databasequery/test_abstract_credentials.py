"""Tests for credential resolution in database sources.

Updated for FEAT-105: AbstractSchemaManagerTool no longer exists;
credential handling is done via AbstractDatabaseSource.resolve_credentials
and get_default_credentials (per-source).

Part of FEAT-105 — databasetoolkit-clash / TASK-738.
"""
import os
import pytest
from unittest.mock import patch, AsyncMock


# ---------------------------------------------------------------------------
# PostgresSource credential resolution
# ---------------------------------------------------------------------------

PG_ENV = {
    "PG_HOST": "db.example.com",
    "PG_PORT": "5433",
    "PG_DATABASE": "mydb",
    "PG_USER": "admin",
    "PG_PWD": "secret",
}


@pytest.mark.asyncio
async def test_pg_explicit_credentials_pass_through():
    """PostgresSource.resolve_credentials returns explicit creds unchanged."""
    from parrot.tools.databasequery.sources.postgres import PostgresSource
    src = PostgresSource()
    explicit = {"host": "explicit-host", "port": "5432", "database": "testdb"}
    result = await src.resolve_credentials(explicit)
    assert result == explicit


@pytest.mark.asyncio
async def test_resolve_credentials_none_falls_back_to_defaults():
    """When credentials=None, resolve_credentials calls get_default_credentials."""
    from parrot.tools.databasequery.sources.postgres import PostgresSource
    src = PostgresSource()
    default_creds = {"host": "localhost", "database": "default_db"}
    with patch.object(src, "get_default_credentials", AsyncMock(return_value=default_creds)):
        result = await src.resolve_credentials(None)
    assert result == default_creds


# ---------------------------------------------------------------------------
# Source instantiation (smoke)
# ---------------------------------------------------------------------------

def test_all_sources_have_driver_attribute():
    """Every registered source has a non-empty .driver class attribute."""
    from parrot.tools.databasequery.sources import get_source_class
    drivers = [
        "pg", "mysql", "sqlite", "bigquery", "oracle",
        "clickhouse", "duckdb", "mssql", "mongo", "documentdb",
        "atlas", "influx", "elastic",
    ]
    for driver in drivers:
        cls = get_source_class(driver)
        instance = cls()
        assert instance.driver == driver, (
            f"Source for '{driver}' has .driver='{instance.driver}'"
        )
