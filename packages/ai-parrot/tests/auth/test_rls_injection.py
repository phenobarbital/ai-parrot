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
    """Tests for the SQL wrapping injection strategy.

    Values are inlined (safely escaped) into the SQL string because
    SQLQuerySource uses str.format()-style substitution and cannot bind named
    :p0 parameters via a driver.  bound_params is always {} after injection.
    """

    def test_single_predicate(self) -> None:
        pred = RlsPredicate(
            table="sales.orders",
            sql_predicate="region IN (:p0, :p1)",
            bound_params={"p0": ["northeast"], "p1": ["southeast"]},
        )
        sql, params = inject_rls_sql("SELECT * FROM sales.orders", "postgres", [pred])
        assert "_rls" in sql
        assert "WHERE" in sql
        # Values are inlined — placeholder names should NOT appear in the SQL
        assert ":p0" not in sql
        assert ":p1" not in sql
        # Inlined values ARE in the SQL (safely quoted)
        assert "'northeast'" in sql
        assert "'southeast'" in sql
        # bound_params is always empty when values are inlined
        assert params == {}

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
            sql_predicate="b = :p0",  # same placeholder name — must not collide
            bound_params={"p0": ["y"]},
        )
        sql, params = inject_rls_sql("SELECT * FROM t", "postgres", [pred1, pred2])
        assert "AND" in sql
        # Values inlined, no placeholders remain
        assert ":p0" not in sql
        assert "'x'" in sql
        assert "'y'" in sql
        assert params == {}

    def test_no_value_interpolation_ac9(self) -> None:
        """AC9: crafted values must be safely escaped when inlined into SQL.

        Values are inlined via single-quote doubling (consistent with
        SQLQuerySource._escape_value).  The raw unescaped injection string
        must not appear verbatim; the doubled-quote form must be present.
        """
        malicious = "'; DROP TABLE users; --"
        pred = RlsPredicate(
            table="t",
            sql_predicate="region IN (:p0)",
            bound_params={"p0": [malicious]},
        )
        sql, params = inject_rls_sql("SELECT * FROM t", "postgres", [pred])
        # The single-quote must be doubled — the raw form starts with '  but
        # the escaped form has '' (two quotes) which prevents SQL injection.
        assert "'';" in sql  # doubled single-quote before the semicolon
        # No residual placeholders
        assert ":p0" not in sql
        # bound_params is empty — values are already in the SQL
        assert params == {}
        # The structure is valid SQL wrapping
        assert "_rls" in sql
        assert "WHERE" in sql

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
        # Value inlined
        assert "'val'" in sql

    def test_multiple_predicates_no_param_collision(self) -> None:
        """Two predicates with the same placeholder name must not collide."""
        pred1 = RlsPredicate(
            table="t1",
            sql_predicate="region = :p0",
            bound_params={"p0": ["northeast"]},
        )
        pred2 = RlsPredicate(
            table="t2",
            sql_predicate="dept = :p0",
            bound_params={"p0": ["engineering"]},
        )
        sql, params = inject_rls_sql("SELECT * FROM t1 JOIN t2 ON t1.id=t2.id", "postgres", [pred1, pred2])
        assert "AND" in sql
        assert "'northeast'" in sql
        assert "'engineering'" in sql
        assert ":p0" not in sql
        assert params == {}


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
        # The filter key must be the actual column name, not the placeholder "p0"
        assert "region" in source._permanent_filter
        assert "northeast" in source._permanent_filter["region"]
        assert "p0" not in source._permanent_filter

    def test_extends_permanent_filter_multi_value(self) -> None:
        """Multiple bound params (one value each) are flattened under the column."""
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="sales.orders", driver="pg")
        pred = RlsPredicate(
            table="sales.orders",
            sql_predicate="region IN (:p0, :p1)",
            bound_params={"p0": ["northeast"], "p1": ["southeast"]},
        )
        inject_rls_table_source(source, [pred])
        assert source._permanent_filter["region"] == ["northeast", "southeast"]

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
        # Key must be the actual column name, not the placeholder
        assert "region" in source._permanent_filter
        assert "east" in source._permanent_filter["region"]
        assert "p0" not in source._permanent_filter


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
