"""Tests for the Physical-Resource Resolver (FEAT-228 / TASK-1491)."""
from __future__ import annotations

import pytest
import sqlglot

from parrot.tools.dataset_manager.sources.resolver import (
    PhysicalResources,
    ReadOnlyViolation,
    physical_tables,
    resolve_physical_resources,
)


class TestPhysicalTables:
    """Tests for the pure ``physical_tables()`` function."""

    def test_simple_select(self) -> None:
        result = physical_tables("SELECT * FROM sales.orders", "postgres")
        assert result == {"sales.orders"}

    def test_join(self) -> None:
        sql = (
            "SELECT a.id FROM sales.orders a "
            "JOIN hr.employees b ON a.emp_id = b.id"
        )
        result = physical_tables(sql, "postgres")
        assert result == {"sales.orders", "hr.employees"}

    def test_cte_alias_excluded(self) -> None:
        sql = """
        WITH recent AS (SELECT * FROM sales.orders WHERE dt > '2024-01-01')
        SELECT * FROM recent JOIN hr.employees ON recent.emp_id = hr.employees.id
        """
        result = physical_tables(sql, "postgres")
        assert "recent" not in result
        assert "sales.orders" in result
        assert "hr.employees" in result

    def test_subquery(self) -> None:
        sql = "SELECT * FROM (SELECT id FROM finance.accounts) sub"
        result = physical_tables(sql, "postgres")
        assert "finance.accounts" in result

    def test_union(self) -> None:
        sql = "SELECT id FROM sales.us UNION ALL SELECT id FROM sales.eu"
        result = physical_tables(sql, "postgres")
        assert result == {"sales.us", "sales.eu"}

    def test_drop_raises_read_only(self) -> None:
        with pytest.raises(ReadOnlyViolation):
            physical_tables("DROP TABLE sales.orders", "postgres")

    def test_update_raises_read_only(self) -> None:
        with pytest.raises(ReadOnlyViolation):
            physical_tables("UPDATE sales.orders SET status = 'x'", "postgres")

    def test_insert_raises_read_only(self) -> None:
        with pytest.raises(ReadOnlyViolation):
            physical_tables("INSERT INTO sales.orders VALUES (1)", "postgres")

    def test_invalid_sql_raises_parse_error(self) -> None:
        with pytest.raises(sqlglot.errors.ParseError):
            physical_tables("NOT VALID SQL AT ALL !!!", "postgres")

    def test_nested_cte(self) -> None:
        """Tables inside CTEs are captured but CTE aliases are not."""
        sql = """
        WITH base AS (SELECT * FROM finance.txns),
             summary AS (SELECT * FROM base GROUP BY region)
        SELECT * FROM summary
        """
        result = physical_tables(sql, "postgres")
        assert "finance.txns" in result
        assert "base" not in result
        assert "summary" not in result


class TestResolvePhysicalResources:
    """Tests for the dispatcher ``resolve_physical_resources()``."""

    def test_sql_source_returns_driver_and_tables(self) -> None:
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource

        source = SQLQuerySource(
            sql="SELECT * FROM sales.orders",
            driver="pg",
        )
        result = resolve_physical_resources(source)
        assert result.driver == "pg"
        assert "pg:sales.orders" in result.tables

    def test_table_source_returns_single_table(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="hr.employees", driver="pg")
        result = resolve_physical_resources(source)
        assert result.driver == "pg"
        assert result.tables == {"pg:hr.employees"}

    def test_in_memory_source_returns_empty(self) -> None:
        import pandas as pd
        from parrot.tools.dataset_manager.sources.memory import InMemorySource

        source = InMemorySource(pd.DataFrame({"a": [1]}), "test")
        result = resolve_physical_resources(source)
        assert result.driver is None
        assert result.tables == set()

    def test_query_slug_source_returns_empty(self) -> None:
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        source = QuerySlugSource(slug="my_slug")
        result = resolve_physical_resources(source)
        assert result.driver is None
        assert result.tables == set()

    def test_sql_source_unknown_dialect_returns_driver_only(self) -> None:
        """Unknown dialect → driver returned, tables not resolved."""
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource

        source = SQLQuerySource(sql="SELECT 1", driver="my_exotic_db")
        result = resolve_physical_resources(source)
        # The exotic driver is normalised but unknown → no dialect mapping
        assert result.tables == set()
        # driver is still set (normalised form)
        assert result.driver is not None
