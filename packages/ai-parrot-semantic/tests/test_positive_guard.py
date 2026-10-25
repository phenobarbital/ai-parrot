"""Regression contract: Projection masks and positive SQL guard (M6c) — positive guard."""

from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp, parse_one
from sqlglot.optimizer.qualify import qualify

from parrot.semantic.errors import SemanticValidationError
from parrot.semantic.governance.guard import (
    DEFAULT_ALLOWED_FUNCTIONS,
    PositiveGuard,
    effective_allowed_functions,
)
from parrot.semantic.governance.lineage import resolve_column_uses
from parrot.semantic.governance.masking import apply_masks
from parrot.semantic.loader import PhysicalSchema
from parrot.semantic.models import Limits
from parrot.semantic.policy import MaskRule, ModelPolicy

DIALECTS = ("postgres", "bigquery", "duckdb")


def _schema() -> PhysicalSchema:
    """Physical schema shared by guard tests."""
    return PhysicalSchema(
        driver="pg",
        tables={
            "sales.orders": {"id": "INT", "customer_id": "INT", "amount": "INT", "ts": "TIMESTAMP"},
            "sales.customers": {"id": "INT", "email": "TEXT", "region": "TEXT"},
        },
    )


def _guard(policy: ModelPolicy | None = None, extra: frozenset[str] | None = None) -> PositiveGuard:
    """Build a guard with a small, distinct default and max."""
    return PositiveGuard(
        _schema(), effective_allowed_functions(policy or ModelPolicy(), extra), Limits(default=100, max=500)
    )


def _qualified(sql: str, dialect: str = "postgres") -> exp.Expression:
    """Parse and qualify SQL against the physical schema."""
    return qualify(parse_one(sql, read=dialect), schema=_schema().sqlglot_schema(), dialect=dialect)


def _maybe_qualified(sql: str, dialect: str) -> exp.Expression:
    """Qualify when possible; return the raw parse when qualification itself rejects the SQL."""
    tree = parse_one(sql, read=dialect)
    try:
        return qualify(tree.copy(), schema=_schema().sqlglot_schema(), dialect=dialect)
    except sqlglot.errors.OptimizeError:
        return tree


def _code(guard: PositiveGuard, tree: exp.Expression) -> str:
    """Return the guard error code for a rejected tree."""
    with pytest.raises(SemanticValidationError) as error:
        guard.check_and_limit(tree)
    return error.value.code


def test_mask_strategies_and_derived_projection(tmp_path: Path) -> None:
    """Masking wrappers pass as trusted nodes; the same functions from the caller do not."""
    assert tmp_path.is_dir()
    schema = _schema()
    policy = ModelPolicy(masks={"sales.customers.email": MaskRule(strategy="partial")})
    tree = _qualified("SELECT LOWER(c.email) AS e, c.region FROM sales.customers AS c")
    tree, masked, trusted = apply_masks(tree, resolve_column_uses(tree, schema), policy, frozenset(), "postgres")
    assert masked == ("sales.customers.email",)
    guard = _guard(policy)
    assert guard.check_and_limit(tree, trusted_nodes=trusted) is tree
    assert _code(guard, _qualified("SELECT SUBSTRING(c.email, 1, 2) AS e FROM sales.customers AS c")) == (
        "function_not_allowed"
    )
    # Compiler-owned CASE and FILTER constructs are structural, not caller functions.
    case = _qualified(
        "SELECT CASE WHEN o.amount > 10 THEN 'big' ELSE 'small' END AS size, "
        "COUNT(*) FILTER (WHERE o.amount > 10) AS n FROM sales.orders AS o GROUP BY 1"
    )
    guard.check_and_limit(case)


def test_allowlist_and_limits(tmp_path: Path) -> None:
    """Default and additive allowlist, statement shape, schema and LIMIT handling."""
    assert tmp_path.is_dir()
    assert {"SUM", "COUNT", "DATE_TRUNC", "CAST"} <= DEFAULT_ALLOWED_FUNCTIONS
    policy = ModelPolicy(allowed_functions=["round"])
    allowed = effective_allowed_functions(policy, frozenset({"abs"}))
    assert DEFAULT_ALLOWED_FUNCTIONS <= allowed and {"ROUND", "ABS"} <= allowed

    guard = _guard()
    assert _code(guard, _qualified("SELECT ROUND(o.amount) AS r FROM sales.orders AS o")) == "function_not_allowed"
    _guard(policy).check_and_limit(_qualified("SELECT ROUND(o.amount) AS r FROM sales.orders AS o"))
    assert _code(guard, _qualified("SELECT PG_SLEEP(1) AS s FROM sales.orders AS o")) == "function_not_allowed"

    ok = guard.check_and_limit(
        _qualified("SELECT DATE_TRUNC('month', o.ts) AS m, COUNT(DISTINCT o.id) AS n FROM sales.orders AS o GROUP BY 1")
    )
    assert ok.args["limit"].expression.this == "100"
    clamped = guard.check_and_limit(_qualified("SELECT o.id FROM sales.orders AS o LIMIT 9999"))
    assert clamped.args["limit"].expression.this == "500"
    kept = guard.check_and_limit(_qualified("SELECT o.id FROM sales.orders AS o LIMIT 7"))
    assert kept.args["limit"].expression.this == "7"

    assert _code(guard, _qualified("SELECT o.id FROM sales.secret AS o")) == "unknown_table"
    assert _code(guard, parse_one("SELECT o.nope FROM sales.orders AS o")) == "unknown_column"
    assert _code(
        guard, _qualified("SELECT o.id FROM sales.orders AS o UNION SELECT c.id FROM sales.customers AS c")
    ) == ("not_select")
    for statement in (
        "DELETE FROM sales.orders",
        "INSERT INTO sales.orders (id) VALUES (1)",
        "UPDATE sales.orders SET amount = 1",
        "DROP TABLE sales.orders",
        "CREATE TABLE x AS SELECT 1",
    ):
        assert _code(guard, parse_one(statement)) == "command_forbidden", statement
    assert _code(guard, exp.Command(this="VACUUM")) == "command_forbidden"
    assert _code(guard, parse_one("SELECT o.id INTO evil FROM sales.orders AS o")) == "command_forbidden"
    assert _code(guard, parse_one("SELECT 1; DROP TABLE sales.orders")) == "command_forbidden"
    assert _code(guard, parse_one("SELECT o.id FROM sales.orders AS o; SELECT c.id FROM sales.customers AS c")) == (
        "not_select"
    )


@pytest.mark.parametrize("dialect", DIALECTS)
def test_three_dialect_adversarial_matrix(tmp_path: Path, dialect: str) -> None:
    """Star, aliases, case/quoted identifiers, CTEs, subqueries, windows and derived projections."""
    assert tmp_path.is_dir()
    q = "`" if dialect == "bigquery" else '"'
    guard = _guard()
    accepted = [
        "SELECT * FROM sales.orders AS o",
        "SELECT o.amount AS total FROM sales.orders AS o ORDER BY total",
        "SELECT O.AMOUNT FROM SALES.ORDERS AS O" if dialect != "bigquery" else "SELECT o.amount FROM sales.orders AS o",
        "WITH x AS (SELECT o.amount AS a FROM sales.orders AS o) SELECT x.a FROM x",
        "SELECT s.a FROM (SELECT o.amount AS a FROM sales.orders AS o) AS s",
        "SELECT SUM(o.amount) OVER (PARTITION BY o.customer_id) AS w FROM sales.orders AS o",
        "SELECT o.id FROM sales.orders AS o JOIN sales.customers AS c ON o.customer_id = c.id",
        "SELECT o.id /* comment */ FROM sales.orders AS o -- trailing",
    ]
    for sql in accepted:
        tree = guard.check_and_limit(_qualified(sql, dialect))
        assert tree.args["limit"] is not None, sql
        assert tree.sql(dialect=dialect)

    rejected = {
        "WITH x AS (SELECT o.amount AS a FROM sales.hidden AS o) SELECT x.a FROM x": "unknown_table",
        "SELECT s.a FROM (SELECT MD5(o.amount) AS a FROM sales.orders AS o) AS s": "function_not_allowed",
        "SELECT o.id FROM sales.orders AS o WHERE o.id IN (SELECT h.id FROM sales.hidden AS h)": "unknown_table",
        "SELECT ROW_NUMBER() OVER (ORDER BY o.id) AS r FROM sales.orders AS o": "function_not_allowed",
    }
    for sql, code in rejected.items():
        tree = _maybe_qualified(sql, dialect)
        assert _code(guard, tree) == code, sql

    # Quoted mixed-case identifiers: postgres treats them case-sensitively (unknown objects); other dialects may
    # normalize them. Either way the guard only ever accepts a tree whose physical sources are known.
    for sql, code in (
        (f"SELECT o.amount FROM {q}Sales{q}.{q}Orders{q} AS o", "unknown_table"),
        (f"SELECT o.{q}Amount{q} FROM sales.orders AS o", "unknown_column"),
    ):
        tree = _maybe_qualified(sql, dialect)
        if dialect == "postgres":
            assert _code(guard, tree) == code, sql
            continue
        try:
            guard.check_and_limit(tree)
        except SemanticValidationError as error:
            assert error.code == code, sql
        else:
            assert {table.name for table in tree.find_all(exp.Table)} == {"orders"}
            assert {column.name for column in tree.find_all(exp.Column)} <= set(_schema().tables["sales.orders"])
    assert _code(guard, _maybe_qualified(f"SELECT o.{q}salary{q} FROM sales.orders AS o", dialect)) == "unknown_column"

    # Unexpanded star (never qualified) is refused rather than trusted.
    assert _code(guard, parse_one("SELECT * FROM sales.orders", read=dialect)) == "unknown_column"
