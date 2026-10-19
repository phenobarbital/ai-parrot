"""Positive SQL guard tests."""

from __future__ import annotations

import pytest
import sqlglot

from parrot.semantic.errors import SemanticValidationError
from parrot.semantic.governance.guard import DEFAULT_ALLOWED_FUNCTIONS, PositiveGuard, effective_allowed_functions
from parrot.semantic.loader import PhysicalSchema
from parrot.semantic.models import Limits
from parrot.semantic.policy import ModelPolicy

SCHEMA = PhysicalSchema(driver="duckdb", tables={"sales.orders": {"region": "TEXT", "amount": "DOUBLE"}})


@pytest.mark.parametrize("dialect", ["postgres", "bigquery", "duckdb"])
@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM sales.orders",
        "SELECT pg_sleep(10) FROM sales.orders",
        "SELECT secret FROM sales.orders",
        "SELECT 1 FROM other.t",
        "SELECT * FROM sales.orders",
        "SELECT SeCrEt FROM sales.orders",
        "SELECT region FROM sales.orders UNION ALL SELECT region FROM sales.orders",
    ],
)
def test_positive_guard_adversarial_matrix(dialect: str, sql: str) -> None:
    """Reject common bypass attempts consistently in every supported dialect."""
    guard = PositiveGuard(SCHEMA, DEFAULT_ALLOWED_FUNCTIONS, Limits())
    with pytest.raises(SemanticValidationError):
        guard.check_and_limit(sqlglot.parse_one(sql, dialect=dialect))


@pytest.mark.parametrize("dialect", ["postgres", "bigquery", "duckdb"])
def test_positive_guard_accepts_ctes_subqueries_windows_and_comments(dialect: str) -> None:
    """Admit safe SELECT structure while checking its physical leaves."""
    sql = (
        "WITH regional AS (SELECT region, amount FROM sales.orders /* safe */) "
        "SELECT region, SUM(amount) OVER (PARTITION BY region) AS total FROM regional"
    )
    guarded = PositiveGuard(SCHEMA, DEFAULT_ALLOWED_FUNCTIONS, Limits(default=25, max=100)).check_and_limit(
        sqlglot.parse_one(sql, dialect=dialect)
    )
    assert guarded.args["limit"].expression.this == "25"


def test_positive_guard() -> None:
    """Inject the default limit and clamp excessive existing or requested limits."""
    guard = PositiveGuard(SCHEMA, DEFAULT_ALLOWED_FUNCTIONS, Limits(default=50, max=100))

    injected = guard.check_and_limit(sqlglot.parse_one("SELECT region FROM sales.orders"))
    clamped = guard.check_and_limit(sqlglot.parse_one("SELECT region FROM sales.orders LIMIT 999999"))
    requested = guard.check_and_limit(
        sqlglot.parse_one("SELECT region FROM sales.orders LIMIT 10"), requested_limit=500
    )

    assert injected.args["limit"].expression.this == "50"
    assert clamped.args["limit"].expression.this == "100"
    assert requested.args["limit"].expression.this == "100"


def test_count_star_and_quoted_known_identifiers_are_allowed() -> None:
    """Allow COUNT(*) and known quoted identifiers without admitting projected wildcards."""
    tree = sqlglot.parse_one('SELECT COUNT(*), "region" FROM "sales"."orders"', dialect="postgres")
    PositiveGuard(SCHEMA, DEFAULT_ALLOWED_FUNCTIONS, Limits()).check_and_limit(tree)


def test_unbound_column_is_rejected() -> None:
    """Do not admit a schema column unless the current SELECT binds its table."""
    with pytest.raises(SemanticValidationError, match="unknown_column"):
        PositiveGuard(SCHEMA, DEFAULT_ALLOWED_FUNCTIONS, Limits()).check_and_limit(sqlglot.parse_one("SELECT region"))


def test_policy_allowed_functions_additive() -> None:
    """Policy extensions widen the defaults and cannot remove SUM."""
    policy = ModelPolicy(connection="warehouse", allowed_functions=["REGEXP_REPLACE"])
    allowed = effective_allowed_functions(policy, frozenset({"ROUND"}))

    assert {"SUM", "REGEXP_REPLACE", "ROUND"}.issubset(allowed)
    guard = PositiveGuard(SCHEMA, allowed, Limits())
    guard.check_and_limit(sqlglot.parse_one("SELECT REGEXP_REPLACE(region, 'x', 'y') FROM sales.orders"))
