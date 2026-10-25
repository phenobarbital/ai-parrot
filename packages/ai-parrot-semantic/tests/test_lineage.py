"""Regression contract for full physical-column usage lineage."""

from pathlib import Path

import pytest
from sqlglot import parse_one
from sqlglot.optimizer.qualify import qualify

from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.governance.lineage import ColumnUse, enforce_usage_rights, resolve_column_uses
from parrot.semantic.loader import PhysicalSchema
from parrot.semantic.policy import ModelPolicy


def _schema() -> PhysicalSchema:
    """Return the physical schema shared by lineage tests."""
    return PhysicalSchema(
        driver="pg",
        tables={
            "sales.orders": {"id": "INT", "customer_id": "INT", "region": "TEXT", "salary": "INT"},
            "sales.customers": {"id": "INT", "region": "TEXT"},
        },
    )


def _uses(sql: str) -> list[ColumnUse]:
    """Qualify SQL and resolve its physical column uses."""
    schema = _schema()
    tree = qualify(parse_one(sql), schema=schema.sqlglot_schema(), validate_qualify_columns=False)
    return resolve_column_uses(tree, schema)


def test_manifest_and_exact_evaluator_failure(tmp_path: Path) -> None:
    """Fail closed when qualified lineage references an unknown physical column."""
    assert tmp_path.is_dir()
    schema = _schema()
    tree = parse_one("SELECT o.missing FROM sales.orders AS o")
    with pytest.raises(SemanticAccessError) as error:
        resolve_column_uses(tree, schema)
    assert error.value.code == "unresolved_lineage"


def test_cte_alias_physical_resources(tmp_path: Path) -> None:
    """Carry WHERE usage through CTE and subquery projection aliases."""
    assert tmp_path.is_dir()
    uses = _uses("""
        WITH compensation AS (
            SELECT o.salary * 2 AS annual_pay
            FROM sales.orders AS o
        )
        SELECT c.annual_pay
        FROM (SELECT annual_pay FROM compensation) AS c
        WHERE c.annual_pay > 100
        """)
    assert ColumnUse(column="salary", table="sales.orders", context="where") in uses
    assert ColumnUse(column="salary", table="sales.orders", context="derived") in uses
    assert all(use.table != "compensation" for use in uses)


def test_sensitive_usage_lineage_matrix(tmp_path: Path) -> None:
    """Deny masked-column inference across every non-projection context."""
    assert tmp_path.is_dir()
    cases = {
        "where": "SELECT o.id FROM sales.orders o WHERE o.salary > 1",
        "having": "SELECT o.region FROM sales.orders o GROUP BY o.region HAVING MAX(o.salary) > 1",
        "join": ("SELECT o.id FROM sales.orders o JOIN sales.customers c " "ON o.salary = c.id"),
        "group_by": "SELECT COUNT(*) FROM sales.orders o GROUP BY o.salary",
        "order_by": "SELECT o.salary AS pay FROM sales.orders o ORDER BY pay",
        "window": "SELECT SUM(o.id) OVER (PARTITION BY o.salary) FROM sales.orders o",
        "derived": "SELECT o.salary * 2 AS pay FROM sales.orders o",
    }
    policy = ModelPolicy.model_validate(
        {
            "connection": "warehouse",
            "roles": {"analyst": {"usage": "*"}},
            "masks": {"sales.orders.salary": {"strategy": "null"}},
        }
    )
    for context, sql in cases.items():
        uses = _uses(sql)
        assert ColumnUse(column="salary", table="sales.orders", context=context) in uses
        with pytest.raises(SemanticAccessError) as error:
            enforce_usage_rights(uses, policy, frozenset({"analyst"}), trusted_nodes={id(uses[0])})
        assert error.value.code == "usage_denied"
        assert error.value.details == {"column": "sales.orders.salary"}

    allowed = ModelPolicy.model_validate(
        {
            "connection": "warehouse",
            "roles": {"analyst": {"usage": ["sales.orders.salary"]}},
            "masks": {"sales.orders.salary": {"strategy": "null", "usage_roles": ["analyst"]}},
        }
    )
    enforce_usage_rights(_uses(cases["where"]), allowed, frozenset({"analyst"}), trusted_nodes=set())
