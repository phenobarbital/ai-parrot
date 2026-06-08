"""Tests for the Driver–Dialect Map (FEAT-228 / TASK-1490)."""
from __future__ import annotations

import pytest

from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect


class TestDriverToDialect:
    """Verify the driver → sqlglot dialect mapping."""

    @pytest.mark.parametrize(
        "driver,expected",
        [
            # Canonical names
            ("pg", "postgres"),
            ("mysql", "mysql"),
            ("bigquery", "bigquery"),
            ("mssql", "tsql"),
            ("oracle", "oracle"),
            ("snowflake", "snowflake"),
            ("redshift", "redshift"),
            ("clickhouse", "clickhouse"),
            ("duckdb", "duckdb"),
            ("sqlite", "sqlite"),
            ("trino", "trino"),
            ("presto", "presto"),
            ("spark", "spark"),
            ("databricks", "databricks"),
            # Raw aliases resolved via normalize_driver
            ("postgres", "postgres"),
            ("postgresql", "postgres"),
            ("mariadb", "mysql"),
            ("bq", "bigquery"),
            ("sqlserver", "tsql"),
        ],
    )
    def test_known_drivers(self, driver: str, expected: str) -> None:
        """Known driver aliases should return the correct sqlglot dialect."""
        assert driver_to_dialect(driver) == expected

    def test_unknown_driver_returns_none(self) -> None:
        """Unknown drivers must return None, not raise."""
        assert driver_to_dialect("unknown_db_xyz") is None

    def test_case_insensitive(self) -> None:
        """Driver names should be normalised case-insensitively."""
        assert driver_to_dialect("BIGQUERY") == "bigquery"
        assert driver_to_dialect("Pg") == "postgres"
        assert driver_to_dialect("MySQL") == "mysql"
