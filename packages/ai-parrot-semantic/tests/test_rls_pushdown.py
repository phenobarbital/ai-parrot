"""RLS push-down tests for governed semantic SQL."""

from __future__ import annotations

from typing import Callable

import pytest
import sqlglot

from parrot.auth import PermissionContext, RlsRegistry, RlsRule
from parrot.auth.rls_registry import RlsPredicate
from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.governance.rls import RlsPushdown
from parrot.semantic.loader import PhysicalSchema

from ._models import duckdb_warehouse  # noqa: F401

SCHEMA = PhysicalSchema(
    driver="duckdb",
    tables={"sales.orders": {"region": "VARCHAR", "amount": "DECIMAL(12, 2)", "customer_id": "BIGINT"}},
)


@pytest.mark.asyncio
async def test_rls_pushdown_below_aggregation(
    duckdb_warehouse: str, pctx_factory: Callable[..., PermissionContext]
) -> None:
    """Filter the base relation before computing grouped aggregate totals."""
    registry = RlsRegistry()
    registry.register(
        RlsRule(
            driver="duckdb",
            table="sales.orders",
            predicate_template="region IN (:subject.programs)",
            subject_attribute="programs",
            description="regional orders",
        )
    )
    tree = sqlglot.parse_one("SELECT region, SUM(amount) AS total FROM sales.orders GROUP BY region", dialect="duckdb")

    rewritten, descriptions, trusted_node_ids = RlsPushdown(registry).apply(
        tree, pctx_factory(programs=["EU"]), "duckdb", schema=SCHEMA
    )

    assert descriptions == ("regional orders",)
    assert trusted_node_ids
    sql = rewritten.sql(dialect="duckdb")
    assert "FROM (SELECT * FROM sales.orders WHERE region IN ('EU')) AS orders" in sql

    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(duckdb_warehouse, read_only=True)
    try:
        result = connection.execute(sql).fetchall()
        expected = connection.execute(
            "SELECT region, SUM(amount) AS total FROM sales.orders WHERE region IN ('EU') GROUP BY region"
        ).fetchall()
    finally:
        connection.close()
    assert result == expected == [("EU", 40)]


def test_rls_typed_literals_and_render_failure(pctx_factory: Callable[..., PermissionContext]) -> None:
    """Quote bound values as literals and surface rendering errors as access denials."""
    predicate = RlsPredicate(
        table="sales.orders",
        sql_predicate="region = :p0 AND customer_id = :p1",
        bound_params={"p0": ["o'brien"], "p1": ["42"]},
    )
    pushdown = RlsPushdown(RlsRegistry())

    condition = pushdown._predicate_expr(predicate, SCHEMA, "sales.orders")

    assert condition.sql(dialect="duckdb") == "region = 'o''brien' AND customer_id = 42"

    class FailingRegistry(RlsRegistry):
        """Registry double whose rendering behavior is a deliberate failure."""

        def render(self, rule: RlsRule, ctx: PermissionContext) -> RlsPredicate:
            """Refuse predicate rendering for the failure-path assertion."""
            del rule, ctx
            raise RuntimeError("unavailable")

    registry = FailingRegistry()
    registry.register(
        RlsRule(
            driver="duckdb",
            table="sales.orders",
            predicate_template="region = :subject.programs",
            subject_attribute="programs",
        )
    )
    with pytest.raises(SemanticAccessError, match="rls_render_failed") as caught:
        RlsPushdown(registry).apply(
            sqlglot.parse_one("SELECT * FROM sales.orders", dialect="duckdb"),
            pctx_factory(programs=["EU"]),
            "duckdb",
            schema=SCHEMA,
        )
    assert caught.value.code == "rls_render_failed"


def test_rls_numeric_literal_rejects_injection() -> None:
    """A subject value for a numeric column is parsed, never emitted verbatim."""
    from parrot.semantic.governance.rls import RlsPushdown

    assert RlsPushdown._literal(" 42 ", "INTEGER").sql() == "42"
    assert RlsPushdown._literal("1.5", "DECIMAL(10,2)").sql() == "1.5"
    for hostile in ("1 OR 1=1", "1; DROP TABLE x", "0x10", "nan", "inf", ""):
        with pytest.raises(ValueError):
            RlsPushdown._literal(hostile, "INTEGER" if hostile != "nan" and hostile != "inf" else "DOUBLE")
    assert RlsPushdown._literal("x' OR '1'='1", "VARCHAR").sql() == "'x'' OR ''1''=''1'"
