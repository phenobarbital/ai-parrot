"""Tests for DatabaseToolkit source registry and driver alias resolution.

Part of FEAT-062 — DatabaseToolkit / TASK-436.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../packages/ai-parrot/src"))

import pytest
from parrot.tools.databasequery.sources import (
    _SOURCE_REGISTRY,
    get_source_class,
    normalize_driver,
    register_source,
)
from parrot.tools.databasequery.base import AbstractDatabaseSource, MetadataResult, QueryResult, RowResult


class TestNormalizeDriver:
    """Tests for driver alias resolution."""

    @pytest.mark.parametrize(
        "alias,expected",
        [
            # Canonical names — idempotent
            ("pg", "pg"),
            ("mysql", "mysql"),
            ("sqlite", "sqlite"),
            ("bigquery", "bigquery"),
            ("mssql", "mssql"),
            ("oracle", "oracle"),
            ("clickhouse", "clickhouse"),
            ("duckdb", "duckdb"),
            ("mongo", "mongo"),
            ("atlas", "atlas"),
            ("documentdb", "documentdb"),
            ("influx", "influx"),
            ("elastic", "elastic"),
            # Aliases
            ("postgres", "pg"),
            ("postgresql", "pg"),
            ("mariadb", "mysql"),
            ("bq", "bigquery"),
            ("sqlserver", "mssql"),
            ("influxdb", "influx"),
            ("mongodb", "mongo"),
            ("elasticsearch", "elastic"),
            ("opensearch", "elastic"),
        ],
    )
    def test_alias_resolution(self, alias: str, expected: str):
        """All driver aliases resolve to their canonical names."""
        assert normalize_driver(alias) == expected

    def test_case_insensitive(self):
        """normalize_driver is case-insensitive."""
        assert normalize_driver("POSTGRES") == "pg"
        assert normalize_driver("PostgreSQL") == "pg"
        assert normalize_driver("ELASTICSEARCH") == "elastic"

    def test_idempotent(self):
        """normalize_driver is idempotent."""
        assert normalize_driver("pg") == "pg"
        assert normalize_driver(normalize_driver("postgresql")) == "pg"

    def test_unknown_driver_passthrough(self):
        """Unknown drivers are returned unchanged (normalized case)."""
        assert normalize_driver("mydb") == "mydb"
        assert normalize_driver("CUSTOM") == "custom"


class TestRegistry:
    """Tests for register_source and get_source_class."""

    def test_register_and_retrieve(self):
        """Decorator registers class in _SOURCE_REGISTRY."""

        @register_source("_test_driver_xyz")
        class FakeSource(AbstractDatabaseSource):
            driver = "_test_driver_xyz"

            async def get_default_credentials(self):
                return {}

            async def get_metadata(self, creds, tables=None):
                return MetadataResult(driver=self.driver, tables=[])

            async def query(self, creds, sql, params=None):
                return QueryResult(driver=self.driver, rows=[], row_count=0, columns=[], execution_time_ms=0.0)

            async def query_row(self, creds, sql, params=None):
                return RowResult(driver=self.driver, row=None, found=False, execution_time_ms=0.0)

        cls = get_source_class("_test_driver_xyz")
        assert cls is FakeSource
        # Cleanup
        _SOURCE_REGISTRY.pop("_test_driver_xyz", None)

    def test_unknown_driver_raises(self):
        """get_source_class raises ValueError for unknown drivers."""
        with pytest.raises(ValueError, match="No DatabaseSource registered"):
            get_source_class("nonexistent_driver_xyz_abc")

    def test_unknown_driver_error_includes_available(self):
        """ValueError message lists available drivers."""
        try:
            get_source_class("nonexistent_driver")
        except ValueError as exc:
            assert "Available" in str(exc) or "available" in str(exc).lower()

    def test_get_source_class_pg(self):
        """get_source_class('pg') returns PostgresSource."""
        cls = get_source_class("pg")
        assert cls.driver == "pg"

    def test_get_source_class_via_alias(self):
        """get_source_class accepts aliases."""
        pg_cls = get_source_class("pg")
        postgres_cls = get_source_class("postgresql")
        assert pg_cls is postgres_cls

    def test_all_canonical_drivers_registered(self):
        """All expected canonical drivers have registered sources."""
        # Trigger lazy loading
        expected_drivers = [
            "pg", "mysql", "sqlite", "bigquery", "oracle",
            "clickhouse", "duckdb", "mssql", "mongo", "documentdb",
            "atlas", "influx", "elastic",
        ]
        for driver in expected_drivers:
            cls = get_source_class(driver)
            assert cls is not None, f"Expected source for '{driver}'"
            assert cls.driver == driver, f"Expected driver='{driver}', got '{cls.driver}'"
