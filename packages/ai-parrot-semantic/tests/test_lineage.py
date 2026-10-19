"""Column lineage and masked-column inference tests."""

from __future__ import annotations

import pytest
import sqlglot
from sqlglot.optimizer.qualify import qualify

from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.governance.lineage import enforce_usage_rights, resolve_column_uses
from parrot.semantic.loader import PhysicalSchema
from parrot.semantic.policy import ModelPolicy

SCHEMA = PhysicalSchema(
    driver="duckdb",
    tables={
        "sales.orders": {
            "customer_id": "INTEGER",
            "department_id": "INTEGER",
            "salary": "DOUBLE",
        },
        "sales.departments": {"id": "INTEGER", "salary": "DOUBLE"},
    },
)
POLICY = ModelPolicy.model_validate(
    {
        "connection": "warehouse",
        "masks": {
            "sales.orders.salary": {
                "strategy": "null",
                "projection_roles": [],
                "usage_roles": ["manager"],
            }
        },
    }
)


def _qualified(sql: str) -> sqlglot.exp.Expression:
    """Parse and qualify a test statement against the physical schema."""
    return qualify(sqlglot.parse_one(sql, dialect="duckdb"), schema=SCHEMA.sqlglot_schema(), dialect="duckdb")


@pytest.mark.parametrize(
    ("sql", "expected_context"),
    [
        ("SELECT customer_id FROM sales.orders WHERE salary > 100", "where"),
        ("SELECT customer_id FROM sales.orders HAVING SUM(salary) > 100", "having"),
        (
            "SELECT o.customer_id FROM sales.orders AS o " "JOIN sales.departments AS d ON o.salary = d.salary",
            "join",
        ),
        ("SELECT salary FROM sales.orders GROUP BY salary", "group_by"),
        ("SELECT salary FROM sales.orders ORDER BY salary", "order_by"),
        (
            "SELECT ROW_NUMBER() OVER (PARTITION BY salary ORDER BY customer_id) AS position " "FROM sales.orders",
            "window",
        ),
        ("SELECT salary AS pay FROM sales.orders ORDER BY pay", "order_by"),
        (
            "WITH compensation AS (SELECT salary FROM sales.orders) "
            "SELECT salary FROM compensation WHERE salary > 100",
            "where",
        ),
        (
            "SELECT doubled FROM (SELECT salary * 2 AS doubled FROM sales.orders) AS compensation",
            "derived",
        ),
    ],
)
def test_lineage_masked_column_inference(sql: str, expected_context: str) -> None:
    """Deny masked salary inference in every non-projection context."""
    uses = resolve_column_uses(_qualified(sql), SCHEMA)

    assert any(
        use.table == "sales.orders" and use.column == "salary" and use.context == expected_context for use in uses
    )
    with pytest.raises(SemanticAccessError, match="usage_denied") as caught:
        enforce_usage_rights(uses, POLICY, frozenset({"analyst"}), trusted_nodes=set())
    assert caught.value.code == "usage_denied"
    assert caught.value.details == {"column": "sales.orders.salary"}


def test_lineage_projection_does_not_require_usage_rights() -> None:
    """A bare projection is governed by projection masking, not usage rights."""
    uses = resolve_column_uses(_qualified("SELECT salary FROM sales.orders"), SCHEMA)

    assert [use.context for use in uses] == ["projection"]
    enforce_usage_rights(uses, POLICY, frozenset({"analyst"}), trusted_nodes=set())


def test_lineage_usage_role_allows_inference() -> None:
    """An explicit mask usage role permits predicate use."""
    uses = resolve_column_uses(_qualified("SELECT customer_id FROM sales.orders WHERE salary > 100"), SCHEMA)

    enforce_usage_rights(uses, POLICY, frozenset({"manager"}), trusted_nodes=set())


def test_lineage_resolves_correlated_subquery() -> None:
    """Resolve an outer physical column referenced by a correlated subquery."""
    uses = resolve_column_uses(
        _qualified(
            "SELECT o.customer_id FROM sales.orders AS o "
            "WHERE EXISTS (SELECT 1 FROM sales.departments AS d WHERE d.salary = o.salary)"
        ),
        SCHEMA,
    )

    assert any(use.table == "sales.orders" and use.column == "salary" and use.context == "where" for use in uses)


def test_lineage_unresolved_column_fails_closed() -> None:
    """Fail closed if an AST column cannot be tied to the declared physical schema."""
    tree = sqlglot.parse_one("SELECT missing FROM sales.orders")

    with pytest.raises(SemanticAccessError, match="unresolved_lineage"):
        resolve_column_uses(tree, SCHEMA)
