"""Tests for RLS Predicate Injection (FEAT-228 / TASK-1494)."""
from __future__ import annotations

import pandas as pd
import pytest

from parrot.auth.rls_registry import RlsPredicate
from parrot.tools.dataset_manager.sources.rls import (
    inject_rls_sql,
    inject_rls_table_source,
    inject_rls_query_slug,
    inject_rls_postfetch,
)


class TestInjectRlsSql:
    """Tests for the SQL wrapping injection strategy."""

    def test_single_predicate(self) -> None:
        pred = RlsPredicate(
            table="sales.orders",
            sql_predicate="region IN (:p0, :p1)",
            bound_params={"p0": ["northeast"], "p1": ["southeast"]},
        )
        sql, params = inject_rls_sql("SELECT * FROM sales.orders", "postgres", [pred])
        assert "_rls" in sql
        assert "WHERE" in sql
        assert ":p0" in sql
        assert ":p1" in sql
        assert params == {"p0": ["northeast"], "p1": ["southeast"]}

    def test_no_predicates_passthrough(self) -> None:
        sql, params = inject_rls_sql("SELECT * FROM sales.orders", "postgres", [])
        assert sql == "SELECT * FROM sales.orders"
        assert params == {}

    def test_multiple_predicates_and(self) -> None:
        pred1 = RlsPredicate(
            table="t1",
            sql_predicate="a = :p0",
            bound_params={"p0": ["x"]},
        )
        pred2 = RlsPredicate(
            table="t2",
            sql_predicate="b = :p1",
            bound_params={"p1": ["y"]},
        )
        sql, params = inject_rls_sql("SELECT * FROM t", "postgres", [pred1, pred2])
        assert "AND" in sql
        assert "p0" in params
        assert "p1" in params

    def test_no_value_interpolation_ac9(self) -> None:
        """AC9: crafted values must not appear in the SQL string."""
        pred = RlsPredicate(
            table="t",
            sql_predicate="region IN (:p0)",
            bound_params={"p0": ["'; DROP TABLE users; --"]},
        )
        sql, params = inject_rls_sql("SELECT * FROM t", "postgres", [pred])
        assert "DROP" not in sql
        assert "'; DROP TABLE users; --" not in sql
        # But the malicious value IS in params — driver will bind it safely
        assert "'; DROP TABLE users; --" in params["p0"]

    def test_wrapped_sql_structure(self) -> None:
        """Wrapped SQL should be 'SELECT * FROM (<orig>) AS _rls WHERE ...'."""
        pred = RlsPredicate(
            table="t",
            sql_predicate="col = :p0",
            bound_params={"p0": ["val"]},
        )
        sql, _ = inject_rls_sql("SELECT id FROM orders", "postgres", [pred])
        assert sql.startswith("SELECT * FROM (")
        assert "SELECT id FROM orders" in sql
        assert "_rls" in sql


class TestInjectRlsTableSource:
    """Tests for permanent_filter extension on TableSource."""

    def test_extends_permanent_filter(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="sales.orders", driver="pg")
        pred = RlsPredicate(
            table="sales.orders",
            sql_predicate="region IN (:p0)",
            bound_params={"p0": ["northeast"]},
        )
        result = inject_rls_table_source(source, [pred])
        assert result is source  # in-place mutation
        assert "p0" in source._permanent_filter

    def test_empty_predicates_unchanged(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="t", driver="pg", permanent_filter={"x": 1})
        inject_rls_table_source(source, [])
        assert source._permanent_filter == {"x": 1}


class TestInjectRlsQuerySlug:
    """Tests for permanent_filter extension on QuerySlugSource."""

    def test_merges_into_slug_conditions(self) -> None:
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        source = QuerySlugSource(slug="my_slug")
        pred = RlsPredicate(
            table="t",
            sql_predicate="region IN (:p0)",
            bound_params={"p0": ["east"]},
        )
        result = inject_rls_query_slug(source, [pred])
        assert result is source
        assert "p0" in source._permanent_filter


class TestInjectRlsPostfetch:
    """Tests for post-fetch DataFrame row filtering."""

    def test_filters_rows(self) -> None:
        df = pd.DataFrame(
            {
                "region": ["northeast", "southeast", "west"],
                "amount": [100, 200, 300],
            }
        )
        pred = RlsPredicate(
            table="t",
            sql_predicate="region IN (:p0, :p1)",
            bound_params={"p0": ["northeast"], "p1": ["southeast"]},
        )
        result = inject_rls_postfetch(df, [pred])
        assert len(result) == 2
        assert "west" not in result["region"].values

    def test_empty_predicates_returns_all(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = inject_rls_postfetch(df, [])
        assert len(result) == 3

    def test_empty_dataframe_returns_empty(self) -> None:
        df = pd.DataFrame({"region": pd.Series([], dtype=str)})
        pred = RlsPredicate(
            table="t",
            sql_predicate="region IN (:p0)",
            bound_params={"p0": ["east"]},
        )
        result = inject_rls_postfetch(df, [pred])
        assert result.empty
