"""Regression contract: Request-local RLS below aggregation (M6b)."""

from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

from parrot.auth import PermissionContext, RlsPredicate, RlsRegistry, RlsRule, UserSession
from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.governance.rls import RlsPushdown
from parrot.semantic.loader import PhysicalSchema


def _context(user_id: str, **metadata: list[str]) -> PermissionContext:
    """Build an isolated trusted subject for one RLS request."""
    return PermissionContext(
        session=UserSession(
            user_id=user_id,
            tenant_id="tenant-1",
            roles=frozenset({"analyst"}),
            metadata=metadata,
        )
    )


def _schema() -> PhysicalSchema:
    """Return the qualified physical schema used by push-down tests."""
    return PhysicalSchema(
        driver="pg",
        tables={
            "sales.orders": {"amount": "DECIMAL(12,2)", "customer_id": "INT", "region": "TEXT"},
            "sales.customers": {"id": "INT", "segment": "TEXT"},
        },
    )


def _registry(*rules: RlsRule) -> RlsRegistry:
    """Build a registry containing the supplied rules."""
    registry = RlsRegistry()
    for rule in rules:
        registry.register(rule)
    return registry


def _rule(table: str, column: str, attribute: str, description: str) -> RlsRule:
    """Create an IN-list RLS rule for one physical table."""
    return RlsRule(
        driver="pg",
        table=table,
        predicate_template=f"{column} IN (:subject.{attribute})",
        subject_attribute=attribute,
        description=description,
    )


def test_rls_below_sum_for_two_subjects(tmp_path: Path) -> None:
    """Wrap each joined base scan below SUM and render subjects independently."""
    assert tmp_path.is_dir()
    registry = _registry(
        _rule("sales.orders", "region", "regions", "orders by region"),
        _rule("sales.customers", "segment", "segments", "customers by segment"),
    )
    pushdown = RlsPushdown(registry)
    original = sqlglot.parse_one(
        "SELECT SUM(n.amount) AS total FROM "
        "(SELECT o.amount, o.customer_id FROM sales.orders AS o) AS n "
        "JOIN sales.customers AS c ON n.customer_id = c.id"
    )
    original_sql = original.sql()

    east, descriptions, trusted = pushdown._for_schema(_schema()).apply(
        original, _context("east-user", regions=["east"], segments=["retail"]), "pg"
    )
    west, _, _ = pushdown._for_schema(_schema()).apply(
        original, _context("west-user", regions=["west"], segments=["enterprise"]), "pg"
    )

    assert original.sql() == original_sql
    assert descriptions == ("customers by segment", "orders by region")
    assert "WHERE region IN ('east')" in east.sql()
    assert "WHERE segment IN ('retail')" in east.sql()
    assert "WHERE region IN ('west')" in west.sql()
    assert "WHERE segment IN ('enterprise')" in west.sql()
    assert east.sql().index("WHERE region") > east.sql().index("FROM sales.orders")
    assert east.sql().index("WHERE region") < east.sql().index("JOIN (SELECT * FROM sales.customers")
    assert len(list(east.find_all(exp.Subquery))) >= 3
    assert trusted
    assert all(any(id(node) == node_id for node in east.walk()) for node_id in trusted)


def test_typed_literals_and_render_failure(tmp_path: Path) -> None:
    """Type numeric/string literals safely, deny absent values, and map render failures."""
    assert tmp_path.is_dir()
    numeric = _registry(_rule("sales.orders", "customer_id", "customer_ids", "customer scope"))
    numeric_tree, _, _ = RlsPushdown(numeric)._for_schema(_schema()).apply(
        sqlglot.parse_one("SELECT SUM(o.amount) FROM sales.orders AS o"),
        _context("numeric-user", customer_ids=["7"]),
        "pg",
    )
    assert "customer_id IN (7)" in numeric_tree.sql()

    malicious = "east'); DROP TABLE sales.orders; --"
    text = _registry(_rule("sales.orders", "region", "regions", "region scope"))
    text_tree, _, _ = RlsPushdown(text)._for_schema(_schema()).apply(
        sqlglot.parse_one("SELECT SUM(o.amount) FROM sales.orders AS o"),
        _context("text-user", regions=[malicious]),
        "pg",
    )
    parsed_again = sqlglot.parse_one(text_tree.sql())
    literal = next(node for node in parsed_again.find_all(exp.Literal) if node.is_string)
    assert literal.this == malicious
    assert len(sqlglot.parse(text_tree.sql())) == 1

    denied, _, _ = RlsPushdown(text)._for_schema(_schema()).apply(
        sqlglot.parse_one("SELECT SUM(o.amount) FROM sales.orders AS o"),
        _context("missing-user"),
        "pg",
    )
    assert "WHERE 1 = 0" in denied.sql()

    class FailingRegistry(RlsRegistry):
        """Registry whose renderer represents a provider/configuration failure."""

        def render(self, rule: RlsRule, ctx: PermissionContext) -> RlsPredicate:
            """Raise instead of returning a rendered predicate."""
            del rule, ctx
            raise ValueError("render failed")

    failing = FailingRegistry()
    failing.register(_rule("sales.orders", "region", "regions", "region scope"))
    with pytest.raises(SemanticAccessError) as error:
        RlsPushdown(failing)._for_schema(_schema()).apply(
            sqlglot.parse_one("SELECT SUM(o.amount) FROM sales.orders AS o"),
            _context("failed-user", regions=["east"]),
            "pg",
        )
    assert error.value.code == "rls_render_failed"


def test_unsupported_sources_and_ast_isolation(tmp_path: Path) -> None:
    """Reject ambiguous sources and keep schema/input state request-local."""
    assert tmp_path.is_dir()
    pushdown = RlsPushdown(_registry(_rule("sales.orders", "region", "regions", "region scope")))
    unsupported = (
        "SELECT * FROM UNNEST(ARRAY[1, 2]) AS u(x)",
        "SELECT * FROM LATERAL (SELECT 1) AS x",
        "SELECT * FROM GENERATE_SERIES(1, 3)",
        "SELECT * FROM (VALUES (1)) AS v(x)",
        "WITH RECURSIVE t AS (SELECT 1 UNION ALL SELECT x + 1 FROM t) SELECT * FROM t",
    )
    for sql in unsupported:
        with pytest.raises(SemanticAccessError) as error:
            pushdown._for_schema(_schema()).apply(sqlglot.parse_one(sql), _context("user", regions=["east"]), "pg")
        assert error.value.code == "rls_unplaceable"

    original = sqlglot.parse_one("SELECT o.amount FROM sales.orders AS o")
    original_sql = original.sql()
    first = pushdown._for_schema(_schema())
    rewritten, _, _ = first.apply(original, _context("user", regions=["east"]), "pg")
    other_schema = PhysicalSchema(driver="pg", tables={"archive.orders": {"region": "TEXT"}})
    untouched, descriptions, trusted = pushdown._for_schema(other_schema).apply(
        original, _context("user", regions=["west"]), "pg"
    )

    assert original.sql() == original_sql
    assert rewritten.sql() != original_sql
    assert untouched.sql() == original_sql
    assert descriptions == ()
    assert trusted == set()
    with pytest.raises(SemanticAccessError) as error:
        pushdown.apply(original, _context("user", regions=["east"]), "pg")
    assert error.value.code == "rls_unplaceable"
