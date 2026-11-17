"""Regression contract: Projection masks and positive SQL guard (M6c) — masking."""

from pathlib import Path

import pytest
from sqlglot import exp, parse_one
from sqlglot.optimizer.qualify import qualify

from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.governance.guard import PositiveGuard, effective_allowed_functions
from parrot.semantic.governance.lineage import resolve_column_uses
from parrot.semantic.governance.masking import apply_masks
from parrot.semantic.loader import PhysicalSchema
from parrot.semantic.models import Limits
from parrot.semantic.policy import MaskRule, ModelPolicy

DIALECTS = ("postgres", "bigquery", "duckdb")


def _schema() -> PhysicalSchema:
    """Physical schema shared by masking tests."""
    return PhysicalSchema(
        driver="pg",
        tables={
            "sales.customers": {"id": "INT", "email": "TEXT", "ssn": "TEXT", "phone": "TEXT", "region": "TEXT"},
            "sales.orders": {"id": "INT", "customer_id": "INT", "amount": "INT"},
        },
    )


def _policy() -> ModelPolicy:
    """Policy masking email (hash), ssn (null) and phone (partial); admin is exempt."""
    return ModelPolicy(
        allowed_functions=[],
        masks={
            "sales.customers.email": MaskRule(strategy="hash", projection_roles=["admin"]),
            "sales.customers.ssn": MaskRule(strategy="null", projection_roles=["admin"]),
            "sales.customers.phone": MaskRule(strategy="partial", projection_roles=["admin"]),
        },
    )


def _mask(sql: str, dialect: str = "postgres", roles: frozenset[str] = frozenset({"analyst"})):
    """Qualify, resolve lineage and mask a query."""
    schema = _schema()
    tree = qualify(parse_one(sql, read=dialect), schema=schema.sqlglot_schema(), dialect=dialect)
    uses = resolve_column_uses(tree, schema)
    return apply_masks(tree, uses, _policy(), roles, dialect)


def test_mask_strategies_and_derived_projection(tmp_path: Path) -> None:
    """Null / hash / partial strategies, derived projections and the admin exemption."""
    assert tmp_path.is_dir()
    tree, masked, trusted = _mask("SELECT c.email, c.ssn, c.phone, c.region FROM sales.customers AS c")
    assert masked == ("sales.customers.email", "sales.customers.phone", "sales.customers.ssn")
    email, ssn, phone, region = tree.expressions
    assert email.alias == "email" and isinstance(email.this, exp.MD5)
    assert ssn.alias == "ssn" and isinstance(ssn.this, exp.Null)
    assert phone.alias == "phone" and isinstance(phone.this, exp.Concat)
    assert isinstance(region, exp.Alias) and isinstance(region.this, exp.Column)
    assert id(email.this) in trusted and id(phone.this) in trusted
    # The caller's column inside the hash wrapper is never trusted.
    assert all(id(column) not in trusted for column in email.find_all(exp.Column))

    # Derived projection: the whole expression is masked and its caller function is not trusted.
    tree, masked, trusted = _mask("SELECT UPPER(c.email) AS shout FROM sales.customers AS c")
    assert masked == ("sales.customers.email",)
    shout = tree.expressions[0]
    assert shout.alias == "shout" and isinstance(shout.this, exp.MD5)
    upper = next(shout.find_all(exp.Upper))
    assert id(upper) not in trusted

    # Exempt role sees raw values; nothing injected.
    tree, masked, trusted = _mask("SELECT c.email FROM sales.customers AS c", roles=frozenset({"admin"}))
    assert masked == () and trusted == set()
    assert isinstance(tree.expressions[0].this, exp.Column)


def test_allowlist_and_limits(tmp_path: Path) -> None:
    """Masking functions pass the guard only as trusted nodes; a caller MD5 does not."""
    assert tmp_path.is_dir()
    schema = _schema()
    guard = PositiveGuard(schema, effective_allowed_functions(_policy(), None), Limits(default=10, max=50))
    tree, _, trusted = _mask("SELECT c.email, c.phone FROM sales.customers AS c")
    guarded = guard.check_and_limit(tree, trusted_nodes=trusted)
    assert guarded.args["limit"].expression.this == "10"

    caller = qualify(parse_one("SELECT MD5(c.region) AS h FROM sales.customers AS c"), schema=schema.sqlglot_schema())
    with pytest.raises(Exception) as error:
        guard.check_and_limit(caller, trusted_nodes=trusted)
    assert getattr(error.value, "code", None) == "function_not_allowed"


@pytest.mark.parametrize("dialect", DIALECTS)
def test_three_dialect_adversarial_matrix(tmp_path: Path, dialect: str) -> None:
    """Star, aliases, quoted identifiers, CTEs, subqueries and windows never leak a masked column."""
    assert tmp_path.is_dir()
    q = '"' if dialect != "bigquery" else "`"
    cases = [
        "SELECT * FROM sales.customers AS c",
        "SELECT c.email AS contact FROM sales.customers AS c",
        f"SELECT {q}c{q}.{q}email{q} FROM sales.customers AS {q}c{q}",
        "WITH x AS (SELECT c.email AS e FROM sales.customers AS c) SELECT x.e FROM x",
        "SELECT s.e FROM (SELECT c.email AS e FROM sales.customers AS c) AS s",
        "SELECT MAX(c.email) OVER (PARTITION BY c.region) AS w FROM sales.customers AS c",
        "SELECT COALESCE(c.email, c.region) AS mixed FROM sales.customers AS c",
    ]
    for sql in cases:
        tree, masked, _ = _mask(sql, dialect)
        assert "sales.customers.email" in masked, sql
        rendered = tree.sql(dialect=dialect)
        for projection in tree.expressions:
            if any(column.name == "email" for column in projection.find_all(exp.Column)):
                assert isinstance(projection.this, exp.MD5), (sql, rendered)

    # A projection whose lineage cannot be traced is denied, not passed through.
    schema = _schema()
    raw = parse_one("SELECT c.email FROM sales.customers AS c", read=dialect)
    uses = resolve_column_uses(qualify(raw.copy(), schema=schema.sqlglot_schema(), dialect=dialect), schema)
    with pytest.raises(SemanticAccessError):
        apply_masks(parse_one("SELECT * FROM sales.customers", read=dialect), uses, _policy(), frozenset(), dialect)
